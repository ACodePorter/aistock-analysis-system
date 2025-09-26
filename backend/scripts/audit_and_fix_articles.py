#!/usr/bin/env python3
"""
使用 Azure OpenAI 和现有爬虫对新闻文章进行质检与修复（强制 LLM 实际调用）。

流程：
- GET http://localhost:8080/api/news/articles?limit=50&offset=0&include_content=true
- 对每篇文章用 Azure OpenAI 判断：是否中文财经、标题/摘要一致性、是否包含关键财经论点、是否有价值
- 如有问题：重新爬取网页 → 用 LLM 针对标题进行信息提取 → 替换 summary，并在 entities 中加入 main_topics 与 detailed_content

用法（默认演练，不写库）:
        python backend/scripts/audit_and_fix_articles.py --limit 50 --offset 0
应用更改:
        python backend/scripts/audit_and_fix_articles.py --apply --limit 50 --offset 0

环境：
- 必须配置 Azure OpenAI（或本地 LLM），否则脚本会直接退出
  AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY, 以及 AZURE_OPENAI_DEPLOYMENT/ AZURE_OPENAI_MODEL
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx

# 确保能导入 `app` 包
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

from app.db import SessionLocal  # type: ignore
from app.models import NewsArticle  # type: ignore
from app.news_service import NewsProcessor  # type: ignore
from app.llm_processor import LLMNewsProcessor  # type: ignore


@dataclass
class JudgeResult:
        is_chinese_finance: bool
        title_summary_coherent: bool
        has_financial_key_points: bool
        is_valuable: bool
        problems: List[str]


JUDGE_PROMPT = (
        "你是一名资深中文财经编辑。请仅根据给定的标题与摘要进行快速质检，严格返回JSON。\n"
        "输入：\n"
        "标题：__TITLE_REPLACE_\n"
        "摘要：__SUMMARY_REPLACE_\n\n"
        "判断要点：\n"
        "1) 是否为中文财经新闻（涉及A股/港股/宏观/行业/公司/市场）\n"
        "2) 标题的主体与摘要是否存在相关性（不要求强相关）\n"
        "3) 摘要是否包含关键财经论点（业绩、估值、政策、交易、投融资、并购、价格变动、指标数据等）、企业行业新闻、政府政策相关内容\n"
        "4) 该摘要是否有一定财经信息价值\n\n"
        "仅返回如下严格JSON：\n"
        "{\n"
        "  \"is_chinese_finance\": true/false,\n"
        "  \"title_summary_coherent\": true/false,\n"
        "  \"has_financial_key_points\": true/false,\n"
        "  \"is_valuable\": true/false,\n"
        "  \"problems\": [\"列举问题点\"]\n"
        "}"
)


async def judge_article(llm: LLMNewsProcessor, title: str, summary: str, art_id: Optional[int]) -> Optional[JudgeResult]:
        """使用 LLM 对文章标题与摘要进行快速质检（优先 Responses API；失败则回退到 analyze_news）。"""
        # 优先：Responses API，严格按 JSON 判断
        try:
                # Replace title and summary in JUDGE_PROMPT
                prompt = JUDGE_PROMPT.replace("__TITLE_REPLACE_", title or "无标题").replace("__SUMMARY_REPLACE_", summary or "无摘要")

                text = await llm._call_azure_openai_responses(prompt)  # noqa: SLF001 intentional
                # print(f"Judge response: {text}")
                if text:
                        s = text.strip()
                        start = s.find("{")
                        end = s.rfind("}")
                        if start != -1 and end != -1 and end > start:
                                s = s[start : end + 1]
                        data = json.loads(s)
                        return JudgeResult(
                                is_chinese_finance=bool(data.get("is_chinese_finance", False)),
                                title_summary_coherent=bool(data.get("title_summary_coherent", False)),
                                has_financial_key_points=bool(data.get("has_financial_key_points", False)),
                                is_valuable=bool(data.get("is_valuable", False)),
                                problems=list(data.get("problems", []) or []),
                        )
        except Exception as e:
                print(f"Judge via Responses API failed: {e}, trying fallback...")
                # 继续尝试回退路径
                pass

        # 回退：调用 analyze_news（同样会使用 LLM），并基于输出做规则判定
        try:
                content_for_judge = summary or title
                res = await llm.analyze_news(title=title or "", content=content_for_judge or "")
                if not res:
                        return None
                cat_ok = (res.category or "").lower() in {"finance", "policy", "industry", "company", "market", "economic"}
                key_points = bool((res.financial_metrics or {}).get("mentioned_values") or (res.financial_metrics or {}).get("percentages") or (res.keywords or []))
                valuable = (res.relevance_score or 0) >= 0.2 or (res.content_quality or 0) >= 0.4

                return JudgeResult(
                        is_chinese_finance=cat_ok,
                        title_summary_coherent=True,  # 回退路径无法精准判断，给出宽松值
                        has_financial_key_points=key_points,
                        is_valuable=valuable,
                        problems=[] if (cat_ok and key_points and valuable) else ["fallback_judge_uncertain"],
                )
        except Exception:
                print("Judge via analyze_news failed")
                return None


async def fetch_articles(base_url: str, limit: int, offset: int, include_content: bool = True) -> List[Dict[str, Any]]:
        # 从后端 API 拉取文章列表（可选择是否包含内容）
        # 后端接口限制每次最大 200 条
        safe_limit = max(1, min(int(limit), 200))
        url = f"{base_url.rstrip('/')}/api/news/articles?limit={safe_limit}&offset={offset}&include_content={'true' if include_content else 'false'}"
        async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.get(url)
                r.raise_for_status()
                data = r.json()
                return data.get("articles", [])


async def recrawl_and_enrich(processor: NewsProcessor, llm: LLMNewsProcessor, title: str, url: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """重新爬取页面、抽取内容，并通过 LLM 分析以生成新的摘要和实体信息。"""
        try:
                soup = await processor._fetch_soup(url)  # noqa: SLF001
                if not soup:
                        return None, None
                content = await processor._extract_content(url, soup)  # noqa: SLF001

                print(f"Re-crawled content length: {len(content) if content else 0}")
                # print start and end 50 chars of content
                
                # 内容太短则跳过
                if not content:
                        return None, None
                res = await llm.analyze_news(title=title or "", content=content or "", url=url)
                print(f" Analyze result: {res} ")
                if not res:
                        return None, None
                
                new_summary = res.summary or None
                  
                print("==============================")

                print(f"LLM analysis result: {new_summary}")

                print("==============================")
                entities = {
                        "companies": res.companies or [],
                        "people": res.people or [],
                        "locations": res.locations or [],
                        "financial_metrics": res.financial_metrics or {},
                        "main_topics": (res.main_topics or [])[:5],
                        "time_references": res.time_references or [],
                        "reliability_assessment": res.reliability_assessment or None,
                        "market_impact": res.market_impact or None,
                        # 附加富文本块，帮助 UI 展示详细话题（限制长度以防过大）
                        "detailed_content": content[:6000],
                }

                print(f"Extracted entities: {entities}")
                return new_summary, entities
        except Exception:
                return None, None


def merge_entities(old: Optional[Dict[str, Any]], new: Dict[str, Any]) -> Dict[str, Any]:
        # 将旧的 entities 与新的数据合并（浅合并，优先使用新值）
        old = old if isinstance(old, dict) else {}
        merged = {**old}
        for k, v in new.items():
                if v is None:
                        continue
                merged[k] = v
        return merged


async def main():
        parser = argparse.ArgumentParser(description="使用 Azure OpenAI 对新闻文章进行质检与修复")
        parser.add_argument("--base-url", default="http://localhost:8080", help="后端基础 URL")
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument("--offset", type=int, default=0)
        parser.add_argument("--apply", action="store_true", help="将修复写入数据库；默认仅演练")
        parser.add_argument("--max", dest="max_items", type=int, default=None, help="可选：处理条目上限")
        parser.add_argument("--concurrency", type=int, default=3, help="并发度（LLM 与抓取有全局限流，建议 2-5）")
        parser.add_argument("--require-llm", action="store_true", default=True, help="无 LLM 配置则直接退出（默认开启）")
        parser.add_argument("--no-require-llm", dest="require_llm", action="store_false", help="允许在无 LLM 配置时继续运行（仅做规则判定）")
        parser.add_argument("--only-id", type=int, default=None, help="只处理指定的文章 ID（用于定点调试）")
        args = parser.parse_args()

        base_url = args.base_url
        limit = args.limit
        offset = args.offset
        apply_changes = args.apply

        print(f"Fetching articles from {base_url} ... limit={min(max(1, limit), 200)} offset={offset}")
        articles = await fetch_articles(base_url, limit, offset, include_content=True)
        if args.max_items is not None:
                articles = articles[: args.max_items]
        print(f"Fetched {len(articles)} articles")

        processor = NewsProcessor()
        updated = 0
        problematic = 0
        judged = 0

        async with LLMNewsProcessor() as llm:
                # 若无 LLM 配置，按参数选择直接退出，避免“judge: failed (skip)”的假阴性
                if args.require_llm and getattr(llm, "llm_service", "none") == "none":
                        print("✗ 未检测到 LLM 配置（AZURE_OPENAI_*）。请设置环境变量后重试，或添加 --no-require-llm 继续。")
                        return

                sem = asyncio.Semaphore(max(1, int(args.concurrency)))

                async def process_one(art: Dict[str, Any]):
                        nonlocal updated, problematic, judged
                        async with sem:
                                art_id = art.get("id")
                                title = art.get("title") or ""
                                summary = art.get("summary") or ""
                                url = art.get("url") or ""

                                # 如果指定 only-id，则跳过不匹配的文章
                                if args.only_id is not None and art_id != args.only_id:
                                        return

                                jr = await judge_article(llm, title, summary, art_id)
                                judged += 1
                                if not jr:
                                        print(f"- [{art_id}] judge: failed (skip)")
                                        return
                                is_ok = all([
                                        jr.is_chinese_finance,
                                        jr.title_summary_coherent,
                                        jr.has_financial_key_points,
                                        jr.is_valuable,
                                ])

                                print(f"- [{art_id}] judge: {'ok' if is_ok else 'problematic'}, key points: {jr.has_financial_key_points}, valuable: {jr.is_valuable}, coherent: {jr.title_summary_coherent}, chinese_finance: {jr.is_chinese_finance}")
                                # 非中文财经：对新浪VIP公司页等保留并尝试抓取；其他来源仍可选择删除
                                if not jr.is_chinese_finance:
                                        host = (url or '').split('/')[2] if '://' in (url or '') else ''
                                        is_sina_vip = host.endswith('vip.stock.finance.sina.com.cn') and '/corp/go.php/' in (url or '')
                                        if is_sina_vip:
                                                print(f"- [{art_id}] not strictly Chinese-finance by judge, but is Sina VIP corp page -> keep & try recrawl")
                                        else:
                                                print(f"- [{art_id}] language: not Chinese finance (skip)")
                                                if apply_changes:
                                                        try:
                                                                with SessionLocal() as session:
                                                                        obj = session.get(NewsArticle, art_id)
                                                                        if obj:
                                                                                session.delete(obj)
                                                                                session.commit()
                                                                                print("  deleted non-cn-finance article")
                                                        except Exception as e:
                                                                print(f"  delete failed: {e}")
                                                else:
                                                        print("  (dry-run) would delete non-cn-finance article")
                                                return

                                # 如判断无问题则跳过
                                if is_ok:
                                        return
                                
                                if summary.strip() != "" and jr.is_chinese_finance:
                                        return

                                print(f"\nProcessing article ID {art_id}: Title: [{title[:60]}], Summary: [{summary}], URL: {url}")


                                problematic += 1
                                print(f"- [{art_id}] problematic -> {','.join(jr.problems) if jr.problems else 'issues'}")

                                new_summary, new_entities = await recrawl_and_enrich(processor, llm, title, url)
                                if not new_summary and not new_entities:
                                        print("  recrawl/enrich failed; skip")
                                        return

                                if apply_changes:
                                        try:
                                                with SessionLocal() as session:
                                                        obj = session.get(NewsArticle, art_id)
                                                        if not obj:
                                                                print("  DB record not found; skip")
                                                                return
                                                        if new_summary:
                                                                obj.summary = new_summary
                                                                # 标记：该摘要由 LLM 生成/修复
                                                                if hasattr(obj, 'summary_from_llm'):
                                                                        obj.summary_from_llm = True
                                                        if new_entities:
                                                                old_entities = obj.entities if isinstance(obj.entities, dict) else {}
                                                                obj.entities = merge_entities(old_entities, new_entities)
                                                        session.add(obj)
                                                        session.commit()
                                                        updated += 1
                                                        print("  updated")
                                        except Exception as e:
                                                print(f"  update failed: {e}")
                                else:
                                        print("  (dry-run) would update summary/entities")

                await asyncio.gather(*(process_one(a) for a in articles))

        print("\nSummary:")
        print(json.dumps({
                "judged": judged,
                "problematic": problematic,
                "updated": updated,
                "dry_run": not apply_changes,
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
        try:
                asyncio.run(main())
        except KeyboardInterrupt:
                print("\nInterrupted")
