# 结构检查

检查器只读、不联网，仅依赖 Python 3.10+ 标准库：

```bash
python3 scripts/check_knowledge.py
python3 scripts/check_knowledge.py --json
python3 scripts/check_knowledge.py --root /path/to/CompanyKnowledgeBase
```

退出码 `0` 表示无结构错误，`1` 表示有结构错误；参数错误由 argparse 返回 `2`。提醒与错误分别统计，提醒不改变成功退出码。`check(root)` 返回 `root`、`markdown_files`、`local_links_checked`、`errors`、`warnings`、`issues`；每项问题含严重程度、代码、文件、行号和说明。

## 覆盖范围

- 必需导航文件、本地内联 Markdown 链接和图片目标、常见标题锚点（含中文及重复标题）、手写 `a` / `span` 锚点。
- 百分编码路径、片段、查询参数，以及目录链接的 `README.md` / `index.md` 入口。仓外链接、绝对本地路径（含 Windows 路径和 file URI）和指向仓外的符号链接报错；仓内链接统一使用 `/` 分隔路径。
- 真实知识与备忘的必需元数据、状态、日期和 ID 唯一性；知识的更新日期不能早于创建日期。
- 真实知识须在 [知识导航](../knowledge/index.md) 有链接，备忘须在 [收件箱导航](../inbox/index.md) 有链接；链接可以指向正文片段。

README、index、TEMPLATE 不当作真实条目；文档中的 frontmatter 和 fenced code 不参与链接与标题检查。空库无需添加虚构业务条目。

## 解析边界

这是轻量检查器，不是完整 Markdown / YAML 解析器。链接覆盖常见内联语法，不覆盖引用式链接、HTML 链接、嵌套方括号和任意深度的括号；复杂标题的锚点可能与具体渲染器存在差异。元数据只支持模板规定的 `key: 单行值`，不支持数组、嵌套对象、多行文本或完整 YAML 类型语义。`.git`、`.venv`、`node_modules`、Python 缓存目录不扫描。

外部 URL 不请求、不验证；非 Markdown 文件的片段产生“未验证”提醒。程序不判断来源真实性、技术结论、索引摘要准确性、内容是否重复、知识是否过期，也不证明 Agent 能遵守规则。相关流程见 [行为场景](../tests/behavior-cases.md)，运行测试见 [测试说明](../tests/README.md)。
