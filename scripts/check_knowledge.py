#!/usr/bin/env python3
"""只读检查知识库的链接、内容元数据和导航覆盖。"""

import argparse
import datetime
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit


REQUIRED_FILES = (
    "README.md", "AGENTS.md", "DESIGN.md", "index.md", "questions.md",
    "knowledge/index.md", "inbox/index.md",
)
RESERVED_CONTENT_NAMES = {"readme.md", "index.md", "template.md"}
IGNORED_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}
KNOWLEDGE_FIELDS = {"id", "title", "domain", "created", "updated", "status"}
MEMO_FIELDS = {"id", "title", "recorded", "scope", "status"}
INLINE_LINK = re.compile(
    r"!?\[[^\]\n]*\]\(\s*(<[^>\n]+>|(?:[^()\s]|\([^()\n]*\))+?)"
    r"(?:\s+[\"'][^\n]*?[\"'])?\s*\)"
)


def _without_fences(text):
    """保留行号，屏蔽 fenced code 中的示例链接与标题。"""
    result = []
    fence_character = None
    fence_length = 0
    lines = text.splitlines()
    frontmatter = bool(lines and lines[0].strip() == "---")
    for index, line in enumerate(lines):
        if frontmatter:
            if index > 0 and line.strip() == "---":
                frontmatter = False
            result.append("")
            continue
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence_character:
            if (match and match.group(1)[0] == fence_character
                    and len(match.group(1)) >= fence_length
                    and not match.group(2).strip()):
                fence_character = None
            result.append("")
        elif match:
            fence_character = match.group(1)[0]
            fence_length = len(match.group(1))
            result.append("")
        else:
            result.append(line)
    return result


def _anchors(lines):
    """提取常见 GitHub 标题锚点；重复标题使用 -1、-2 后缀。"""
    anchors = set()
    for index, line in enumerate(lines):
        heading = None
        match = re.match(r"^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if match:
            heading = match.group(1)
        elif (index + 1 < len(lines) and line.strip()
              and re.match(r"^ {0,3}(?:=+|-+)\s*$", lines[index + 1])):
            heading = line.strip()
        for anchor in re.finditer(
                r"<(?:a|span)\b[^>]*\b(?:id|name)=[\"']([^\"']+)[\"']", line):
            anchors.add(anchor.group(1))
        if heading is None:
            continue
        heading = re.sub(r"!?\[([^\]]+)\]\([^)]*\)", r"\1", heading)
        heading = re.sub(r"<[^>]*>", "", heading)
        base = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        candidate = base
        suffix = 1
        while candidate in anchors:
            candidate = f"{base}-{suffix}"
            suffix += 1
        anchors.add(candidate)
    return anchors


def _links(lines):
    """产出行号和内联链接；行内代码不当作真实链接。"""
    for line_number, line in enumerate(lines, 1):
        line = re.sub(r"(`+).*?\1", "", line)
        for match in INLINE_LINK.finditer(line):
            yield line_number, match.group(1).strip("<>")


def _metadata(text):
    """解析本仓模板的简单单行字段，不将它冒充通用 YAML 解析器。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, [(1, "缺少文件开头的 frontmatter")]
    fields = {}
    problems = []
    for number, line in enumerate(lines[1:], 2):
        if line.strip() == "---":
            return fields, problems
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"([a-z][a-z0-9_]*):\s*(.*?)\s*", line)
        if not match:
            problems.append((number, "元数据仅支持 key: 单行值"))
            continue
        key, value = match.groups()
        if key in fields:
            problems.append((number, f"重复元数据字段：{key}"))
        if value[:1] in {"[", "{", "|", ">"}:
            problems.append((number, f"字段 {key} 须使用简单单行值"))
        if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
            value = value[1:-1]
        fields[key] = value
    problems.append((1, "frontmatter 缺少结束分隔线"))
    return fields, problems


def _date(value):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        return None


def check(root):
    """检查 root，返回统计和问题；不修改文件、不访问网络。

    Args:
        root: 知识库根目录路径。

    Returns:
        含 errors、warnings、issues 等字段的可 JSON 序列化字典。
    """
    root = Path(root).resolve()
    issues = []
    texts = {}
    lines_by_file = {}
    links_by_file = {}
    local_links_checked = 0

    def issue(code, file, line, message, severity="error"):
        issues.append({"severity": severity, "code": code, "file": file,
                       "line": line, "message": message})

    if not root.is_dir():
        issue("ROOT_NOT_DIRECTORY", ".", 0, "根目录不存在或不是目录")
    else:
        for required in REQUIRED_FILES:
            if not (root / required).is_file():
                issue("MISSING_REQUIRED_FILE", required, 0, "缺少必需入口文件")
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            if (not path.is_file() or path.suffix.lower() != ".md"
                    or any(part in IGNORED_DIRS for part in relative.parts)):
                continue
            if not path.resolve().is_relative_to(root):
                issue("OUTSIDE_ROOT", relative.as_posix(), 0, "Markdown 文件指向仓库外")
                continue
            try:
                texts[path.resolve()] = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                issue("UNREADABLE_FILE", relative.as_posix(), 0, str(error))
        lines_by_file = {path: _without_fences(text) for path, text in texts.items()}

        for path, lines in lines_by_file.items():
            source = path.relative_to(root).as_posix()
            links_by_file[path] = set()
            for line_number, target in _links(lines):
                try:
                    parsed = urlsplit(target)
                except ValueError:
                    issue("INVALID_LINK", source, line_number, f"无法解析链接：{target}")
                    continue
                if re.match(r"^[a-zA-Z]:[\\/]", target) or parsed.scheme == "file":
                    local_links_checked += 1
                    issue("ABSOLUTE_LOCAL_LINK", source, line_number,
                          f"本地链接须使用仓内相对路径：{target}")
                    continue
                if parsed.scheme or parsed.netloc:
                    continue
                local_links_checked += 1
                target_path = unquote(parsed.path)
                if target_path.startswith(("/", "\\")):
                    issue("ABSOLUTE_LOCAL_LINK", source, line_number,
                          f"本地链接须使用仓内相对路径：{target}")
                    continue
                if "\\" in target_path:
                    issue("BACKSLASH_LOCAL_LINK", source, line_number,
                          f"仓内链接须使用 / 分隔路径：{target}")
                    continue
                destination = (path.parent / target_path).resolve() if target_path else path
                if not destination.is_relative_to(root):
                    issue("OUTSIDE_ROOT", source, line_number, f"链接越出仓库：{target}")
                    continue
                if destination.is_dir():
                    destination = next(
                        (destination / name for name in ("README.md", "index.md")
                         if (destination / name).is_file()), destination)
                if not destination.is_file():
                    issue("BROKEN_LINK", source, line_number, f"目标不存在：{target}")
                    continue
                destination = destination.resolve()
                if not destination.is_relative_to(root):
                    issue("OUTSIDE_ROOT", source, line_number,
                          f"链接目标指向仓库外：{target}")
                    continue
                links_by_file[path].add(destination)
                if parsed.fragment:
                    if destination.suffix.lower() != ".md":
                        issue("UNCHECKED_FRAGMENT", source, line_number,
                              f"未验证非 Markdown 片段：{target}", "warning")
                    elif (destination in lines_by_file
                          and unquote(parsed.fragment) not in _anchors(lines_by_file[destination])):
                        issue("BROKEN_FRAGMENT", source, line_number,
                              f"标题锚点不存在：{target}")

        seen_ids = {}
        for path, text in texts.items():
            relative = path.relative_to(root)
            if (relative.parts[0] not in {"knowledge", "inbox"}
                    or path.name.lower() in RESERVED_CONTENT_NAMES):
                continue
            source = relative.as_posix()
            kind = relative.parts[0]
            fields, problems = _metadata(text)
            for line_number, message in problems:
                issue("INVALID_METADATA", source, line_number, message)
            required = KNOWLEDGE_FIELDS if kind == "knowledge" else MEMO_FIELDS
            for field in sorted(required):
                if not fields.get(field, "").strip():
                    issue("MISSING_METADATA", source, 1, f"缺少非空字段：{field}")
            identifier = fields.get("id", "")
            if identifier:
                prefix = "K-" if kind == "knowledge" else "M-"
                if (not identifier.startswith(prefix) or len(identifier) <= 2
                        or re.search(r"\s", identifier)):
                    issue("INVALID_ID", source, 1, f"id 应以 {prefix} 开头且不含空白")
                if identifier in seen_ids:
                    issue("DUPLICATE_ID", source, 1,
                          f"id 与 {seen_ids[identifier]} 重复：{identifier}")
                seen_ids[identifier] = source
            allowed = ({"draft", "verified", "needs-review"} if kind == "knowledge"
                       else {"recorded", "superseded", "resolved"})
            if fields.get("status") and fields["status"] not in allowed:
                issue("INVALID_STATUS", source, 1,
                      f"status 应为 {', '.join(sorted(allowed))}")
            dates = ("created", "updated") if kind == "knowledge" else ("recorded",)
            parsed_dates = {}
            for field in dates:
                if fields.get(field):
                    parsed_dates[field] = _date(fields[field])
                    if parsed_dates[field] is None:
                        issue("INVALID_DATE", source, 1, f"{field} 应为有效 YYYY-MM-DD 日期")
            if (parsed_dates.get("created") and parsed_dates.get("updated")
                    and parsed_dates["updated"] < parsed_dates["created"]):
                issue("REVERSED_DATES", source, 1, "updated 不能早于 created")
            navigation = (root / kind / "index.md").resolve()
            if path not in links_by_file.get(navigation, set()):
                issue("MISSING_INDEX_ENTRY", source, 0,
                      f"尚未被 {kind}/index.md 的本地链接覆盖")

    return {"root": str(root), "markdown_files": len(texts),
            "local_links_checked": local_links_checked,
            "errors": sum(item["severity"] == "error" for item in issues),
            "warnings": sum(item["severity"] == "warning" for item in issues),
            "issues": issues}


def main(argv=None):
    """命令行入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1],
                        help="知识库根目录（默认脚本所在仓库）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    arguments = parser.parse_args(argv)
    result = check(arguments.root)
    if arguments.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Markdown: {result['markdown_files']}，本地链接: {result['local_links_checked']}，"
              f"错误: {result['errors']}，提醒: {result['warnings']}")
        for item in result["issues"]:
            print(f"{item['severity']} {item['code']} {item['file']}:{item['line']} "
                  f"{item['message']}")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
