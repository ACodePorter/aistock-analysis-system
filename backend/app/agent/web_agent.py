import asyncio
import json
import os
import re
from typing import Any, Dict, List, Optional

from ..news.llm_service_proxy import generate_json, generate_text
from ..retrieval import WebFetchClient, WebReader, WebSearchClient


class AgenticWebRetriever:
    """
    AgenticWebRetriever 类：OpenClaw 风格的网络检索管道

    该类实现了一个多阶段的网络信息检索流程：搜索 -> 获取 -> 阅读 -> 推理
    支持同步和异步操作，集成 LLM 能力进行智能 URL 选择和内容摘要生成。

    主要功能：
    - 网络搜索：通过多个搜索引擎获取初始结果
    - 智能 URL 筛选：基于关键词匹配或 LLM 推理选择最相关的 URL
    - 并发获取：高效地获取多个网页的 HTML 内容
    - 内容提取：将 HTML 转换为可读的纯文本
    - 智能推理：使用 LLM 生成针对问题的内容摘要

    属性:
        search_client (WebSearchClient): 网络搜索客户端
        fetch_client (WebFetchClient): 网页获取客户端
        reader (WebReader): 网页内容阅读器
        max_urls (int): 最大处理的 URL 数量（默认 3）
        search_top_k (int): 搜索返回的初始结果数量（默认 8）
        fetch_concurrency (int): 并发获取网页的线程数（默认 3）
        enable_llm_selector (bool): 是否启用 LLM URL 选择器（默认 False）
        enable_llm_reasoner (bool): 是否启用 LLM 内容推理器（默认 False）
    """

    def __init__(self):
        self.search_client = WebSearchClient()
        self.fetch_client = WebFetchClient()
        self.reader = WebReader()
        self.max_urls = int(os.getenv("WEB_AGENT_MAX_URLS", "3"))
        self.search_top_k = int(os.getenv("WEB_AGENT_SEARCH_TOP_K", "8"))
        self.fetch_concurrency = int(os.getenv("WEB_AGENT_FETCH_CONCURRENCY", "3"))
        self.enable_llm_selector = os.getenv("WEB_AGENT_USE_LLM_SELECTOR", "true").lower() in ("1", "true", "yes")
        self.enable_llm_reasoner = os.getenv("WEB_AGENT_USE_LLM_REASONER", "false").lower() in ("1", "true", "yes")

    async def retrieve(
        self,
        question: str,
        max_results: int = 20,
        category: str = "general",
        time_range: Optional[str] = None,
        language: Optional[str] = None,
        engines: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        search_results = await self.search_client.search(
            query=question,
            top_k=max(self.search_top_k, self.max_urls * 2),
            category=category,
            time_range=time_range,
            language=language,
            engines=engines,
        )
        return await self._build_docs(question, search_results, max_results)

    def retrieve_sync(
        self,
        question: str,
        max_results: int = 20,
        category: str = "general",
        time_range: Optional[str] = None,
        language: Optional[str] = None,
        engines: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return asyncio.run(
            self.retrieve(
                question=question,
                max_results=max_results,
                category=category,
                time_range=time_range,
                language=language,
                engines=engines,
            )
        )

    async def search_only(
        self,
        question: str,
        top_k: int = 10,
        category: str = "general",
        time_range: Optional[str] = None,
        language: Optional[str] = None,
        engines: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return await self.search_client.search(
            query=question,
            top_k=top_k,
            category=category,
            time_range=time_range,
            language=language,
            engines=engines,
        )

    def search_only_sync(
        self,
        question: str,
        top_k: int = 10,
        category: str = "general",
        time_range: Optional[str] = None,
        language: Optional[str] = None,
        engines: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return self.search_client.search_sync(
            query=question,
            top_k=top_k,
            category=category,
            time_range=time_range,
            language=language,
            engines=engines,
        )

    async def health_check(self, query: str = "A股 最新新闻") -> Dict[str, Any]:
        started_results = await self.search_only(question=query, top_k=3)
        docs = await self._build_docs(query, started_results, 1)
        return {
            "ok": bool(started_results),
            "query": query,
            "search_results": len(started_results),
            "readable_results": len(docs),
            "mode": "openclaw_web",
            "providers": getattr(self.search_client, "provider_order", []),
        }

    async def _build_docs(self, question: str, search_results: List[Dict[str, Any]], max_results: int) -> List[Dict[str, Any]]:
        if not search_results:
            return []

        selected_urls = await self._select_urls(question, search_results, self.max_urls)
        if not selected_urls:
            return []

        html_map = await self.fetch_client.fetch_many(selected_urls, concurrency=self.fetch_concurrency)
        docs: List[Dict[str, Any]] = []
        by_url = {row.get("url"): row for row in search_results if isinstance(row, dict)}
        for url in selected_urls:
            html = html_map.get(url)
            if not html:
                continue
            text = self.reader.extract(url, html)
            if not text:
                continue
            base = by_url.get(url, {})
            summary = await self._reason(question, text, base.get("snippet") or "")
            docs.append(
                {
                    "title": base.get("title") or url,
                    "url": url,
                    "snippet": base.get("snippet") or "",
                    "source": base.get("source") or "web",
                    "published": base.get("published"),
                    "content": text,
                    "summary": summary,
                    "retrieval_mode": "openclaw_web",
                    "retrieval_steps": ["search", "fetch", "read", "reason"],
                }
            )
            if len(docs) >= max_results:
                break
        return docs

    async def _select_urls(self, question: str, search_results: List[Dict[str, Any]], top_n: int) -> List[str]:
        if self.enable_llm_selector:
            llm_urls = await self._select_urls_by_llm(question, search_results, top_n)
            if llm_urls:
                return llm_urls[:top_n]

        q_tokens = self._tokenize(question)
        scored: List[tuple] = []
        for row in search_results:
            url = row.get("url")
            if not url:
                continue
            text = f"{row.get('title') or ''} {row.get('snippet') or ''}".lower()
            score = 0
            for token in q_tokens:
                if token in text:
                    score += 1
            scored.append((score, url))
        scored.sort(key=lambda item: item[0], reverse=True)
        urls = [url for _, url in scored if url]
        return urls[:top_n]

    async def _select_urls_by_llm(self, question: str, search_results: List[Dict[str, Any]], top_n: int) -> List[str]:
        """
        使用 LLM 根据用户问题从搜索结果中选择最相关的 URL。

        该方法使用语言模型智能过滤和排序搜索结果，仅返回与用户查询最相关的 URL。

        参数:
            question (str): 用户问题或查询，用于匹配搜索结果。
            search_results (List[Dict[str, Any]]): 搜索结果字典列表，每项包含
                'title'、'url'、'snippet' 和 'source' 字段。
            top_n (int): 返回的 URL 最大数量。

        返回:
            List[str]: 选中的 URL 列表（最多 top_n 条），已验证和清理，确保：
                - 是有效的 HTTP/HTTPS URL
                - 存在于原始搜索结果中
                - 无重复
                - 通过 LLM 相关性过滤

        处理流程:
            1. 从前 10 条搜索结果中提取标题、URL、摘要（最多 300 字）和来源
            2. 向 LLM 发送提示词，请求返回 JSON 格式的相关 URL 列表
            3. 验证 LLM 响应格式和 URL 合法性
            4. 返回清理后、去重的有效 URL 列表，最多 top_n 条

        注意:
            - 使用 temperature=0 确保 LLM 输出的确定性
            - 对格式错误的 LLM 响应进行优雅降级处理，返回空列表
            - 针对原始搜索结果验证 URL，防止注入攻击
        """
        payload = []
        for row in search_results[:10]:
            payload.append(
                {
                    "title": row.get("title"),
                    "url": row.get("url"),
                    "snippet": (row.get("snippet") or "")[:300],
                    "source": row.get("source"),
                }
            )

        prompt = (
            "你是检索代理。请按用户问题从搜索结果中选出最相关的URL。\n"
            f"用户问题: {question}\n"
            f"最多选择: {top_n}\n"
            f"搜索结果: {json.dumps(payload, ensure_ascii=False)}\n"
            "返回JSON，格式: {\"urls\": [\"https://...\"]}，不要返回其他文本。"
        )
        data = await generate_json(prompt=prompt, temperature=0)
        if not isinstance(data, dict):
            return []
        urls = data.get("urls")
        if not isinstance(urls, list):
            return []
        cleaned: List[str] = []
        allowed = {row.get("url") for row in search_results if isinstance(row, dict) and row.get("url")}
        for url in urls:
            if isinstance(url, str) and url.startswith(("http://", "https://")) and url in allowed and url not in cleaned:
                cleaned.append(url)
        return cleaned[:top_n]

    
    async def _reason(self, question: str, content: str, snippet: str) -> str:
        if not self.enable_llm_reasoner:
            base = (snippet or content[:300]).strip()
            return base[:280] + "..." if len(base) > 280 else base

        # 生成摘要时，限制输入内容长度以适应模型上下文窗口，同时保留搜索摘要作为辅助信息

        prompt = (
            "你是网页阅读代理。请根据用户问题，给出简短证据摘要（80-180字）。\n"
            f"用户问题: {question}\n"
            f"网页正文: {(content or '')[:4000]}\n"
            "只返回摘要文本。"
        )
        text = await generate_text(prompt=prompt, temperature=0.2)
        if isinstance(text, str) and text.strip():
            return text.strip()[:500]
        base = (snippet or content[:300]).strip()
        return base[:280] + "..." if len(base) > 280 else base

    def _tokenize(self, text: str) -> List[str]:
        tokens = re.split(r"[\s,.;:!?()\\[\\]{}\"'`|/\\\\]+", (text or "").lower())
        return [token for token in tokens if len(token) >= 2]
