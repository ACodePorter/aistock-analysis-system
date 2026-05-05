"""
股票画像数据富化模块

搜索策略（按优先级）：
1. CompanyProfileSearchService —— 百度百科 / 维基百科 / 新浪财经 / 东方财富等
2. BaikeScraper —— 百度百科专用爬虫（备选）
3. WebSearchClient (DuckDuckGo) —— 通用搜索兜底
4. LLM 分析 —— 对搜集到的信息做结构化提取

核心原则：搜不到有效信息就不写入，不生成占位文本。
"""

import json
import logging
import asyncio
import time
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from ..core.models import StockProfile

logger = logging.getLogger(__name__)


class StockProfileEnricher:
    """股票画像富化器 —— 多源搜索 + LLM 结构化"""

    def __init__(self):
        self._profile_search = None
        self._baike_scraper = None
        self._llm_processor = None

        self._profile_prompt = """你是专业的财经分析师。基于以下关于公司 {company_name} ({symbol}) 的公开信息，生成结构化的企业画像。

【公司基本信息】
- 名称: {company_name}
- 代码: {symbol}

【搜集到的公开资料】
{collected_info}

请严格基于上述资料，按以下 JSON 格式返回分析结果：
{{
    "industry": "所属行业",
    "sub_industry": "细分行业",
    "business_summary": "业务概述（80-200字，必须具体描述：主营业务/产品服务/商业模式/主要客户或应用场景/收入来源至少2项）",
    "core_products": "核心产品或服务，逗号分隔",
    "competitive_position": "市场地位或竞争优势",
    "competitors": "主要竞争对手，逗号分隔",
    "risk_factors": "主要风险因素，逗号分隔",
    "strategic_keywords": "战略关键词，逗号分隔",
    "market_position": "市场表现评价",
    "history_highlights": "历史亮点/里程碑（3-6条，按时间顺序，用分号分隔；没有就留空）"
}}

要求：
- 只基于上面提供的资料分析，资料中没有的信息对应字段留空字符串 ""
- 绝对不要使用"暂无"、"待补充"、"未找到"等占位词
- 如果某字段确实无法从资料中提取，直接写空字符串 ""
- 确保输出为有效 JSON 格式
"""

    def _get_profile_search(self):
        if self._profile_search is None:
            try:
                from ..news.company_profile_service import CompanyProfileSearchService
                self._profile_search = CompanyProfileSearchService()
            except Exception as e:
                logger.warning(f"CompanyProfileSearchService init failed: {e}")
        return self._profile_search

    def _get_baike_scraper(self):
        if self._baike_scraper is None:
            try:
                from ..utils.baike_scraper import BaikeScraper
                self._baike_scraper = BaikeScraper()
            except Exception as e:
                logger.warning(f"BaikeScraper init failed: {e}")
        return self._baike_scraper

    async def _get_llm_processor(self):
        if self._llm_processor is None:
            from ..news.llm_processor import LLMNewsProcessor
            self._llm_processor = LLMNewsProcessor()
        return self._llm_processor

    @staticmethod
    def _convert_symbol_for_profile(symbol: str) -> str:
        """将 '600519.SH' 格式转换为 'SH600519' 格式（CompanyProfileSearchService 需要）。"""
        s = symbol.upper().strip()
        if "." in s:
            code, market = s.split(".", 1)
            return f"{market}{code}"
        return s

    # ------------------------------------------------------------------
    # 多源信息搜集
    # ------------------------------------------------------------------

    async def _collect_company_info(
        self, symbol: str, company_name: str
    ) -> Dict[str, Any]:
        """多源搜集公司信息（轻量直接 HTTP，无 scraper 依赖）。"""
        import httpx
        from urllib.parse import quote
        from bs4 import BeautifulSoup
        from ..services.stock_pool_service import _is_meaningful_value

        collected: Dict[str, Any] = {
            "raw_texts": [],
            "profile_data": {},
            "sources": [],
        }
        timeout = httpx.Timeout(12.0, connect=8.0)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        # ---- 源 1: 东方财富 F10 API（结构化，快速可靠） ----
        try:
            code_num = symbol.split(".")[0]
            market = symbol.split(".")[-1].upper() if "." in symbol else ""
            em_api = (
                f"https://datacenter.eastmoney.com/securities/api/data/v1/get?"
                f"reportName=RPT_F10_ORG_BASICINFO&columns=ALL&filter=(SECUCODE=%22{code_num}.{market}%22)"
            )
            async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as c:
                resp = await c.get(em_api)
                logger.debug(f"[Enrich] EastMoney API resp status={resp.status_code} for {symbol}")
                if resp.status_code == 200:
                    data = resp.json()
                    items = (data.get("result") or {}).get("data") or []
                    logger.debug(f"[Enrich] EastMoney items count={len(items)} for {symbol}")
                    if items:
                        item = items[0]
                        field_map = [
                            ("ORG_NAME", "full_company_name"),
                            ("EM2016", "industry"),
                            ("CSRC_INDUSTRY_NAME", "sector"),
                            ("FOUND_DATE", "founded_date"),
                            ("MAIN_BUSINESS", "business_scope"),
                            ("REG_CAPITAL", "registered_capital"),
                            ("TOTAL_NUM", "employees"),
                            ("ADDRESS", "headquarters"),
                            ("CONTROL_HOLDER", "major_shareholders"),
                            ("CHAIRMAN", "chairman"),
                            ("ORG_PROFILE", "market_position"),
                        ]
                        for em_key, our_key in field_map:
                            v = item.get(em_key)
                            if v and _is_meaningful_value(str(v)):
                                collected["profile_data"][our_key] = str(v)
                        intro = item.get("ORG_PROFIE") or item.get("ORG_PROFILE") or ""
                        biz = item.get("MAIN_BUSINESS") or ""
                        # 仅当简介不是“公司全称复读”时，才作为 description 候选
                        if intro and len(intro) > 30:
                            name_norm = (company_name or "").replace("*", "").replace(" ", "").strip()
                            intro_norm = str(intro).replace(" ", "").strip()
                            if name_norm and intro_norm and intro_norm != name_norm and name_norm not in intro_norm[: max(20, len(name_norm))]:
                                collected["profile_data"]["description"] = str(intro)
                        if intro and len(intro) > 20:
                            collected["raw_texts"].append(f"【企业简介】{intro[:800]}")
                        if biz and len(biz) > 10:
                            collected["raw_texts"].append(f"【主营业务】{biz[:500]}")
                        if collected["raw_texts"]:
                            collected["sources"].append("eastmoney_api")
                            logger.info(f"[Enrich] EastMoney API OK for {symbol}")
        except Exception as e:
            logger.warning(f"[Enrich] EastMoney API failed for {symbol}: {e}", exc_info=True)

        # ---- 源 2: 百度百科 HTML 抓取 ----
        if not collected["raw_texts"]:
            try:
                bk_url = f"https://baike.baidu.com/item/{quote(company_name)}"
                async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as c:
                    resp = await c.get(bk_url)
                    if resp.status_code == 200 and len(resp.text) > 5000:
                        soup = BeautifulSoup(resp.text, "html.parser")
                        desc_tag = soup.select_one("div.lemma-summary, meta[name='description']")
                        if desc_tag:
                            desc = desc_tag.get("content", "") if desc_tag.name == "meta" else desc_tag.get_text(strip=True)
                            if desc and len(desc) > 20:
                                collected["raw_texts"].append(f"【百科摘要】{desc[:500]}")
                                collected["sources"].append("baike")
                                logger.info(f"[Enrich] Baidu Baike OK for {symbol}")
                        info_items = soup.select("dl.basicInfo-block dt, dl.basicInfo-block dd")
                        key = ""
                        for tag in info_items:
                            if tag.name == "dt":
                                key = tag.get_text(strip=True)
                            elif tag.name == "dd" and key:
                                val = tag.get_text(strip=True)
                                if val:
                                    collected["raw_texts"].append(f"【{key}】{val}")
                                key = ""
            except Exception as e:
                logger.debug(f"[Enrich] Baidu Baike failed for {symbol}: {e}")

        # ---- 源 3: DuckDuckGo 搜索兜底（定向补齐缺口） ----
        if not collected["raw_texts"]:
            try:
                from ..retrieval.search import WebSearchClient
                ws_client = WebSearchClient()
                queries = [
                    f"{company_name} 公司简介 主营业务 核心产品",
                    f"{company_name} 里程碑 重大事件 上市 并购",
                    f"{company_name} 竞争对手 同行业 可比公司",
                    f"{company_name} 风险 提示 处罚 诉讼 问询",
                ]
                for q in queries:
                    results = await asyncio.wait_for(ws_client.search(query=q, top_k=5), timeout=20)
                    if not results:
                        continue
                    collected["sources"].append("web_search")
                    for r in results[:2]:
                        snippet = r.get("snippet", "")
                        if snippet and len(snippet) > 30:
                            collected["raw_texts"].append(f"【{r.get('title','')}】{snippet}")
                    # 有足够材料就停
                    if len(collected["raw_texts"]) >= 6:
                        break
            except asyncio.TimeoutError:
                logger.warning(f"[Enrich] WebSearch TIMEOUT for {symbol}")
            except Exception as e:
                logger.debug(f"[Enrich] WebSearch failed for {symbol}: {e}")

        return collected

    # ------------------------------------------------------------------
    # LLM 结构化分析
    # ------------------------------------------------------------------

    async def _analyze_with_llm(
        self, symbol: str, company_name: str, collected_info: str
    ) -> Optional[Dict[str, Any]]:
        """使用 LLM 将搜集到的信息结构化。"""
        try:
            llm = await self._get_llm_processor()
            prompt = self._profile_prompt.format(
                company_name=company_name,
                symbol=symbol,
                collected_info=collected_info,
            )
            if llm.llm_service == "azure":
                response = await llm._call_azure_openai_responses(prompt)
            elif llm.llm_service == "local":
                response = await llm._call_local_llm(prompt)
            else:
                logger.warning("No LLM service available")
                return None

            if not response:
                return None

            return llm._parse_llm_response(response)
        except Exception as e:
            logger.error(f"[Enrich] LLM analysis failed for {symbol}: {e}")
            return None

    # ------------------------------------------------------------------
    # 核心 enrich 方法
    # ------------------------------------------------------------------

    async def enrich_stock_profile(
        self,
        symbol: str,
        company_name: str,
        db: Session,
        force_refresh: bool = False,
        supplementary_info: Optional[str] = None,
    ) -> Optional[StockProfile]:
        """富化单只股票的画像数据。搜集不到有效信息就不写入。
        supplementary_info: 用户手动提供的补充信息，会一并交给 LLM 分析。
        """
        try:
            profile = db.query(StockProfile).filter_by(symbol=symbol).first()

            if profile and not force_refresh and not supplementary_info:
                from ..services.stock_pool_service import (
                    _is_meaningful_value,
                    _calc_profile_completion,
                )
                completion = _calc_profile_completion(profile)
                if (
                    _is_meaningful_value(profile.business_summary)
                    and completion >= 50
                    and profile.last_refreshed
                    and (datetime.utcnow() - profile.last_refreshed) < timedelta(hours=24)
                ):
                    logger.info(
                        f"Profile for {symbol} is fresh (completion={completion}%)"
                    )
                    return profile

            logger.info(f"Enriching profile for {symbol} ({company_name})...")

            # 第一步：多源搜集信息
            collected = await self._collect_company_info(symbol, company_name)
            raw_texts = collected["raw_texts"]
            profile_data = collected.get("profile_data", {})

            # 如果有补充信息或现有画像，即使搜不到新数据也可以让 LLM 重构
            has_supplement = bool(supplementary_info and supplementary_info.strip())
            has_existing_profile = bool(
                profile and any(
                    getattr(profile, f, None)
                    for f in ("business_summary", "industry", "core_products",
                              "competitive_position", "risk_factors")
                )
            )

            if not raw_texts and not profile_data and not has_supplement and not has_existing_profile:
                logger.warning(
                    f"[Enrich] No info found for {symbol} ({company_name}), skipping write"
                )
                return profile

            # 将现有画像信息和用户补充信息加入 raw_texts
            if has_existing_profile and (force_refresh or has_supplement):
                existing_parts = []
                for attr, label in [
                    ("industry", "行业"), ("business_summary", "业务概述"),
                    ("core_products", "核心产品"), ("competitive_position", "市场地位"),
                    ("competitors", "竞争对手"), ("risk_factors", "风险因素"),
                    ("strategic_keywords", "战略关键词"),
                ]:
                    v = getattr(profile, attr, None)
                    if v:
                        existing_parts.append(f"{label}: {v}")
                if existing_parts:
                    raw_texts.insert(0, "【现有画像信息】\n" + "\n".join(existing_parts))

            if has_supplement:
                raw_texts.append(f"【用户补充信息】\n{supplementary_info.strip()}")

            # 第二步：如果 profile_data 已足够丰富且无补充信息，跳过 LLM；否则用 LLM 分析
            from ..services.stock_pool_service import _is_meaningful_value, _is_meaningful_field
            profile_fields_from_data = sum(
                1 for k in ("industry", "description", "business_scope",
                            "founded_date", "headquarters", "employees")
                if _is_meaningful_value(profile_data.get(k))
            ) if profile_data else 0

            llm_analysis = None
            # 缺口驱动：只要关键字段不够“有价值”，就触发 LLM
            need_llm = has_supplement or profile_fields_from_data < 4
            if profile:
                if not _is_meaningful_field("business_summary", getattr(profile, "business_summary", None)):
                    need_llm = True
                if not _is_meaningful_field("history_highlights", getattr(profile, "history_highlights", None)):
                    need_llm = True
            if raw_texts and need_llm:
                info_text = "\n".join(raw_texts)[:3000]
                t0 = time.perf_counter()
                llm_analysis = await self._analyze_with_llm(
                    symbol, company_name, info_text
                )
                t1 = time.perf_counter()
                logger.info("[PERF] profile_llm symbol=%s duration=%.3f", symbol, (t1 - t0))

            # 第三步：合并 profile_data + llm_analysis，写入数据库
            if not profile:
                profile = StockProfile(symbol=symbol, company_name=company_name)

            field_map = {
                "industry": ["industry", "sector"],
                "sub_industry": ["sub_industry", "sector"],
                "business_summary": ["business_summary", "description"],
                "core_products": ["core_products", "business_scope"],
                "competitive_position": ["competitive_position", "market_position"],
                "competitors": ["competitors"],
                "risk_factors": ["risk_factors"],
                "strategic_keywords": ["strategic_keywords"],
                "history_highlights": ["history_highlights"],
            }

            any_field_written = False
            for db_attr, source_keys in field_map.items():
                val = None
                if llm_analysis:
                    for k in source_keys:
                        v = llm_analysis.get(k)
                        if _is_meaningful_field(db_attr, v):
                            val = v
                            break
                if val is None and profile_data:
                    for k in source_keys:
                        v = profile_data.get(k)
                        if _is_meaningful_field(db_attr, v):
                            val = v
                            break
                if val is not None:
                    if db_attr == "business_summary":
                        # 防止把公司全称写入“业务概述”
                        name_norm = (company_name or "").replace("*", "").replace(" ", "").strip().lower()
                        val_norm = str(val).replace(" ", "").strip().lower()
                        if name_norm and (val_norm == name_norm or val_norm in {f"{name_norm}。", f"{name_norm}."}):
                            val = None
                        elif name_norm and len(val_norm) <= max(30, len(name_norm) + 6) and name_norm in val_norm:
                            val = None
                if val is not None:
                    setattr(profile, db_attr, val)
                    any_field_written = True
                else:
                    old_val = getattr(profile, db_attr, None)
                    if old_val and not _is_meaningful_value(old_val):
                        setattr(profile, db_attr, None)

            if llm_analysis:
                # 保留采集到的公司全称（供 API 读取），不依赖单独 DB 列
                if profile_data.get("full_company_name") and not llm_analysis.get("full_company_name"):
                    llm_analysis["full_company_name"] = profile_data.get("full_company_name")
                profile.profile_json = json.dumps(llm_analysis, ensure_ascii=False)
            elif profile_data:
                profile.profile_json = json.dumps(profile_data, ensure_ascii=False)

            if not any_field_written:
                logger.warning(
                    f"[Enrich] All extracted fields are empty/placeholder for {symbol}, skipping DB write"
                )
                return profile

            profile.company_name = company_name
            profile.last_refreshed = datetime.utcnow()
            profile.updated_at = datetime.utcnow()

            db.add(profile)
            t_db0 = time.perf_counter()
            db.commit()
            t_db1 = time.perf_counter()
            db.refresh(profile)
            logger.info("[PERF] profile_db_commit symbol=%s commit_duration=%.3f", symbol, (t_db1 - t_db0))

            logger.info(f"Successfully enriched profile for {symbol}")
            return profile

        except Exception as e:
            db.rollback()
            logger.error(f"Error enriching profile for {symbol}: {e}")
            return None

    # ------------------------------------------------------------------
    # 同步包装器（给后台线程用）
    # ------------------------------------------------------------------

    def enrich_stock_profile_sync(
        self,
        symbol: str,
        company_name: str,
        db: Session,
        force_refresh: bool = False,
        supplementary_info: Optional[str] = None,
    ) -> Optional[StockProfile]:
        """同步包装器，自动适配有/无 event loop 的场景。"""
        coro = self.enrich_stock_profile(
            symbol=symbol,
            company_name=company_name,
            db=db,
            force_refresh=force_refresh,
            supplementary_info=supplementary_info,
        )
        try:
            asyncio.get_running_loop()
            has_loop = True
        except RuntimeError:
            has_loop = False

        try:
            if not has_loop:
                return asyncio.run(coro)
            # 已有 event loop（如被 APScheduler 在 async 环境调用），
            # 在新线程中运行 asyncio.run()
            import threading
            result_box: list = [None]
            err_box: list = [None]

            def _run():
                try:
                    result_box[0] = asyncio.run(coro)
                except Exception as exc:
                    err_box[0] = exc

            t = threading.Thread(target=_run, daemon=True)
            t.start()
            t.join(timeout=120)
            if err_box[0]:
                raise err_box[0]
            return result_box[0]
        except Exception as e:
            logger.error(f"Error in sync wrapper for {symbol}: {e}", exc_info=True)
            return None
