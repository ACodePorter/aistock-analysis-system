# LLM 提示词模板管理

本目录集中管理 AIStock 系统中所有 LLM 提示词模板。

## 目录结构

```text
prompts/
├── README.md                           # 本文件
├── analysis/
│   ├── daily_report_system.md          # 日报生成 — 系统提示词
│   ├── daily_report_user.md            # 日报生成 — 用户提示词模板
│   ├── weekly_report_system.md         # 周报生成 — 系统提示词
│   └── agent_answer_composer.md        # Agent 问答语义聚合
├── news/
│   ├── news_analysis.md                # 新闻结构化分析
│   ├── document_extraction.md          # 公告/文档结构化提取
│   └── search_relevance_filter.md      # 搜索结果相关性过滤
├── profile/
│   ├── stock_profile_enrichment.md     # 股票画像富化
│   └── company_description.md          # 公司描述生成（百科）
└── summary/
    └── tech_report_simplify.md         # 技术分析报告口语化摘要
```

## 文件格式约定

每个提示词文件采用 Markdown 格式，包含以下结构：

1. **元数据头部** — 版本号、用途、调用方、模型要求、参数配置
2. **System Prompt** — 系统角色设定（如有）
3. **User Prompt Template** — 用户输入模板，使用 `{variable}` 占位符
4. **输出格式约束** — 期望的输出格式说明
5. **变更日志** — 版本变更记录

## 占位符规范

- 使用 Python `str.format()` 兼容的 `{variable_name}` 语法
- JSON 模板中的花括号需转义为 `{{` / `}}`
- 常用占位符：
  - `{company_name}` — 公司名称
  - `{symbol}` — 股票代码
  - `{title}` — 标题
  - `{content}` — 正文内容
  - `{collected_info}` — 采集到的资料

## 使用方式

后端代码通过加载模板文件并填充变量来构建最终提示词：

```python
from pathlib import Path

def load_prompt(template_path: str, **kwargs) -> str:
    text = Path(f"prompts/{template_path}").read_text(encoding="utf-8")
    # 提取 prompt 正文（跳过元数据头部）
    # 使用 str.format() 填充变量
    return text.format(**kwargs)
```

## 版本管理

- 每次修改提示词必须更新 `version` 字段和变更日志
- 重大变更（影响输出格式）升级主版本号
- 微调措辞/约束升级次版本号
- 线上验证后方可合入主分支
