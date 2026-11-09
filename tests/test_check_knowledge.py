"""结构检查的边界、只读性与命令行回归测试。"""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_knowledge.py"
SPEC = importlib.util.spec_from_file_location("check_knowledge", SCRIPT)
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


class StructureCheckTest(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for name in CHECKER.REQUIRED_FILES:
            self.write(name, "# 入口\n")

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def knowledge(self, name="training/resume.md", identifier="K-20261109-resume",
                  extra="", created="2026-11-09", updated="2026-11-09"):
        return self.write("knowledge/" + name, f"""---
id: {identifier}
title: 训练恢复
domain: 训练基础设施/状态管理
created: {created}
updated: {updated}
status: draft
{extra}---
# 训练恢复

## 适用条件

待确认。
""")

    def memo(self, identifier="M-20261109-build", scope="示例分支"):
        return self.write("inbox/2026-11/build.md", f"""---
id: {identifier}
title: 构建备忘
recorded: 2026-11-09
scope: {scope}
status: recorded
---
# 构建备忘

用户口述，待核查。
""")

    def codes(self):
        return {item["code"] for item in CHECKER.check(self.root)["issues"]}

    def test_empty_repository_needs_no_fake_content(self):
        result = CHECKER.check(self.root)
        self.assertEqual(result["errors"], 0, result)

    def test_valid_content_and_fragment_index_links(self):
        self.knowledge()
        self.memo()
        self.write("knowledge/index.md", "[恢复](training/resume.md#适用条件)\n")
        self.write("inbox/index.md", "[构建](2026-11/build.md)\n")
        self.write("questions.md", "[恢复影响](knowledge/training/resume.md#适用条件)\n")
        self.assertEqual(CHECKER.check(self.root)["errors"], 0)

    def test_missing_required_file_is_reported(self):
        (self.root / "AGENTS.md").unlink()
        self.assertIn("MISSING_REQUIRED_FILE", self.codes())

    def test_link_target_and_fragment_are_distinguished(self):
        self.write("index.md", "[丢失](missing.md)\n[坏标题](README.md#不存在)\n")
        self.assertIn("BROKEN_LINK", self.codes())
        self.assertIn("BROKEN_FRAGMENT", self.codes())

    def test_chinese_duplicate_and_inline_code_headings(self):
        self.write("README.md", "# 使用方式\n## 命令 `--root`\n## 使用方式\n")
        self.write("index.md", "[中文](README.md#使用方式)\n"
                   "[重复](README.md#使用方式-1)\n[命令](README.md#命令---root)\n")
        self.assertEqual(CHECKER.check(self.root)["errors"], 0)

    def test_fenced_and_inline_code_are_not_links(self):
        self.write("index.md", "```markdown\n[示例](missing.md)\n# 虚构标题\n```\n"
                   "`[代码](missing.md)`\n~~~\n[示例](missing.md)\n~~~\n")
        result = CHECKER.check(self.root)
        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["local_links_checked"], 0)

    def test_code_heading_does_not_create_real_anchor(self):
        self.write("README.md", "```\n# 虚构\n```\n")
        self.write("index.md", "[链接](README.md#虚构)\n")
        self.assertIn("BROKEN_FRAGMENT", self.codes())

    def test_frontmatter_is_not_rendered_as_setext_heading(self):
        self.write("README.md", "---\nstatus: draft\n---\n# 正文\n")
        self.write("index.md", "[假锚点](README.md#status-draft)\n")
        self.assertIn("BROKEN_FRAGMENT", self.codes())

    def test_percent_encoded_paths_query_and_directory_entry(self):
        self.write("docs/有 空格.md", "# 中文标题\n")
        self.write("docs/README.md", "# 文档\n")
        self.write("index.md", "[文件](docs/%E6%9C%89%20%E7%A9%BA%E6%A0%BC.md?view=1#中文标题)\n"
                   "[目录](docs/)\n[带空格](<docs/有 空格.md>)\n")
        self.assertEqual(CHECKER.check(self.root)["errors"], 0)

    def test_external_links_are_not_fetched(self):
        self.write("index.md", "[外部](https://example.invalid/x?q=1#y)\n"
                   "[邮件](mailto:example@example.invalid)\n")
        result = CHECKER.check(self.root)
        self.assertEqual(result["local_links_checked"], 0)
        self.assertEqual(result["errors"], 0)

    def test_escape_and_encoded_escape_are_rejected(self):
        self.write("index.md", "[越界](../outside.md)\n[编码越界](%2e%2e/outside.md)\n"
                   "[绝对](/tmp/outside.md)\n")
        result = CHECKER.check(self.root)
        self.assertEqual(sum(item["code"] == "OUTSIDE_ROOT" for item in result["issues"]), 2)
        self.assertIn("ABSOLUTE_LOCAL_LINK", self.codes())

    def test_windows_and_file_uris_are_not_treated_as_external_links(self):
        self.write("index.md", "[Windows](C:\\private\\note.md)\n"
                   "[文件](file:///private/note.md)\n[反斜杠](docs\\note.md)\n")
        result = CHECKER.check(self.root)
        self.assertEqual(sum(item["code"] == "ABSOLUTE_LOCAL_LINK" for item in result["issues"]), 2)
        self.assertIn("BACKSLASH_LOCAL_LINK", self.codes())

    def test_symlink_target_cannot_escape_repository(self):
        with tempfile.TemporaryDirectory() as outside:
            external = Path(outside) / "external.txt"
            external.write_text("outside", encoding="utf-8")
            (self.root / "outside.txt").symlink_to(external)
            self.write("index.md", "[目标](outside.txt)\n")
            self.assertIn("OUTSIDE_ROOT", self.codes())

    def test_missing_index_entries_report_actual_content(self):
        self.knowledge()
        self.memo()
        result = CHECKER.check(self.root)
        entries = [item for item in result["issues"] if item["code"] == "MISSING_INDEX_ENTRY"]
        self.assertEqual(len(entries), 2)

    def test_reserved_templates_and_examples_are_not_content(self):
        self.write("knowledge/TEMPLATE.md", "# 模板\n")
        self.write("inbox/README.md", "# 使用方法\n")
        self.write("docs/examples.md", "# 虚构示例\n")
        self.assertEqual(CHECKER.check(self.root)["errors"], 0)

    def test_duplicate_ids_are_rejected(self):
        self.knowledge()
        self.knowledge("training/second.md")
        self.assertIn("DUPLICATE_ID", self.codes())

    def test_missing_and_duplicate_metadata_are_reported(self):
        self.write("knowledge/topic.md", "# 没有元数据\n")
        self.knowledge(extra="title: 重复标题\n")
        self.assertIn("MISSING_METADATA", self.codes())
        self.assertIn("INVALID_METADATA", self.codes())

    def test_invalid_dates_order_status_and_prefix_are_rejected(self):
        path = self.knowledge(identifier="M-wrong", created="2026-02-30", updated="2026-11-09")
        self.assertIn("INVALID_DATE", self.codes())
        self.assertIn("INVALID_ID", self.codes())
        path.write_text(path.read_text().replace("draft", "unknown"), encoding="utf-8")
        self.assertIn("INVALID_STATUS", self.codes())
        self.knowledge(created="2026-11-10", updated="2026-11-09")
        self.assertIn("REVERSED_DATES", self.codes())

    def test_memo_requires_scope_and_recorded_date(self):
        path = self.memo(scope="")
        path.write_text(path.read_text().replace("2026-11-09", "2026-13-01"), encoding="utf-8")
        self.assertIn("MISSING_METADATA", self.codes())
        self.assertIn("INVALID_DATE", self.codes())

    def test_non_markdown_fragment_is_warning_only(self):
        self.write("sample.txt", "sample\n")
        self.write("index.md", "[片段](sample.txt#section)\n")
        result = CHECKER.check(self.root)
        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["warnings"], 1)

    def test_check_is_read_only(self):
        self.knowledge()
        before = {str(path.relative_to(self.root)): (path.read_bytes(), path.stat().st_mtime_ns)
                  for path in self.root.rglob("*") if path.is_file()}
        CHECKER.check(self.root)
        after = {str(path.relative_to(self.root)): (path.read_bytes(), path.stat().st_mtime_ns)
                 for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_cli_custom_root_json_and_failure_exit_code(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), "--json"],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["root"], str(self.root.resolve()))
        self.write("index.md", "[坏链接](missing.md)\n")
        result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("BROKEN_LINK", result.stdout)

    def test_invalid_root_returns_structured_error(self):
        result = CHECKER.check(self.root / "missing")
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["issues"][0]["code"], "ROOT_NOT_DIRECTORY")


if __name__ == "__main__":
    unittest.main()
