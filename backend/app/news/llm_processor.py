"""
LLM-powered News Processing System
Advanced news content analysis using Large Language Models
"""

import asyncio
import json
import os
import re
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass, asdict
import logging

import httpx
import time
from ..core.models import NewsCategory, SentimentType


@dataclass
class NewsAnalysisResult:
    """新闻分析结果"""
    # 基本信息
    summary: str
    category: str
    
    # 实体信息
    companies: List[str]
    people: List[str]
    locations: List[str]
    stock_symbols: List[str]
    
    # 情感分析
    sentiment_type: str
    sentiment_score: float
    sentiment_confidence: float
    
    # 主题和关键词
    main_topics: List[str]
    keywords: List[str]
    
    # 财经特定信息
    financial_metrics: Dict[str, Any]
    market_impact: str
    relevance_score: float
    
    # 时间信息
    time_references: List[str]
    
    # 质量评估
    content_quality: float
    reliability_assessment: str


class LLMNewsProcessor:
    """LLM新闻处理器"""
    # 全局并发限制与冷却控制（跨实例共享）
    _sem: Optional[asyncio.Semaphore] = None
    _cooldown_lock: Optional[asyncio.Lock] = None
    _cooldown_until: float = 0.0
    # 全局速率限制（简单滑动窗口：默认每分钟最多 N 次）
    _rate_lock: Optional[asyncio.Lock] = None
    _rate_window_seconds: int = 60
    _rate_limit_per_window: int = 5
    _call_timestamps: List[float] = []
    
    def __init__(self):
        # Azure OpenAI配置
        self.azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.azure_key = os.getenv("AZURE_OPENAI_KEY")
        self.azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4")
        # 严格遵循用户提供的 Responses API 示例，默认 API 版本改为 2025-04-01-preview
        self.azure_api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2025-04-01-preview")
        # Responses API 需要传入 model 参数；优先使用部署名（Azure通常要求传入部署名）
        # 若未设置部署名，则回退到 AZURE_OPENAI_MODEL（默认示例 gpt-5-mini）
        self.azure_model = os.getenv("AZURE_OPENAI_MODEL") or os.getenv("AZURE_OPENAI_DEPLOYMENT") or "gpt-5-mini"
        # 是否优先使用 Responses API
        self.azure_use_responses = (
            os.getenv("AZURE_OPENAI_USE_RESPONSES", "auto").lower() == "true"
            or self.azure_api_version.startswith("2025-")
        )
        # Optional: force JSON mode for better parsing, when supported
        self.azure_force_json = os.getenv("AZURE_OPENAI_FORCE_JSON", "true").lower() in ("1", "true", "yes")
        # 授权头使用方案：responses 示例偏向 Bearer；保持兼容，默认 responses 用 Bearer，chat 用 api-key
        self.azure_auth_scheme = os.getenv("AZURE_OPENAI_AUTH_SCHEME", "auto").lower()  # auto|bearer|api-key
        # 最大补全 token（Responses API 使用 max_completion_tokens）
        try:
            # 严格对齐示例默认值 16384，可由环境变量覆盖
            self.azure_max_completion_tokens = int(os.getenv("AZURE_OPENAI_MAX_COMPLETION_TOKENS", "16384"))
        except Exception:
            self.azure_max_completion_tokens = 16384
        
        # 本地LLM配置（备选）
        self.local_llm_url = os.getenv("LOCAL_LLM_URL")
        
        # 全局HTTP超时
        try:
            timeout_sec = float(os.getenv("AZURE_OPENAI_TIMEOUT", "60"))
        except Exception:
            timeout_sec = 60.0
        self.http_client = httpx.AsyncClient(timeout=timeout_sec)
        # 初始化全局并发与冷却控制
        if LLMNewsProcessor._sem is None:
            try:
                max_conc = int(os.getenv("AZURE_OPENAI_MAX_CONCURRENCY", "2"))
            except Exception:
                max_conc = 2
            LLMNewsProcessor._sem = asyncio.Semaphore(max(1, max_conc))
        if LLMNewsProcessor._cooldown_lock is None:
            LLMNewsProcessor._cooldown_lock = asyncio.Lock()
        self._cooldown_default = float(os.getenv("AZURE_OPENAI_COOLDOWN_SECONDS", "60"))
        # 初始化全局速率限制
        if LLMNewsProcessor._rate_lock is None:
            LLMNewsProcessor._rate_lock = asyncio.Lock()
        try:
            # 每分钟最大调用次数（默认 5）
            LLMNewsProcessor._rate_limit_per_window = int(os.getenv("AZURE_OPENAI_RATE_LIMIT_PER_MINUTE", "5"))
        except Exception:
            LLMNewsProcessor._rate_limit_per_window = 5
        
        # 确定使用的LLM服务
        self.llm_service = self._determine_llm_service()
        
        # 提示词模板
        self.analysis_prompt = self._get_analysis_prompt()
    
    def _determine_llm_service(self) -> str:
        """确定使用哪个LLM服务"""
        if self.azure_endpoint and self.azure_key:
            return "azure"
        elif self.local_llm_url:
            return "local"
        else:
            return "none"
    
    def _get_analysis_prompt(self) -> str:
        """获取新闻分析提示词"""
        return """
你是专业的财经编辑，输出结构化分析并保持“新闻纪要”口吻。

新闻标题: {title}
新闻内容: {content}

按以下 JSON 返回：
{{
    "summary": "50-120字简明摘要。禁止出现：本文/文章/本页面/该页面/我们/模型 等措辞；不要解释方法；用客观、简短的事实句。若页面为行情/模板/数据页，请基于可见参数生成‘数据分析式摘要’，提炼指数涨跌与涨跌幅、成交额/量、资金流向、ETF/板块表现等；不要写‘无实质新闻’。",
    "category": "finance/policy/industry/company/market/economic 之一",
    "companies": ["涉及公司"],
    "people": ["涉及人物"],
    "locations": ["涉及地点"],
    "stock_symbols": ["股票代码，如 002649.SZ"],
    "sentiment_type": "positive/negative/neutral",
    "sentiment_score": -1~1,
    "sentiment_confidence": 0~1,
    "main_topics": ["主要话题"],
    "keywords": ["关键词"],
    "financial_metrics": {{
        "mentioned_values": ["数值"],
        "percentages": ["百分比"],
        "financial_terms": ["术语"]
    }},
    "market_impact": "high/medium/low",
    "relevance_score": 0~1,
    "time_references": ["时间引用"],
    "content_quality": 0~1,
    "reliability_assessment": "high/medium/low"
}}

约束：
- 摘要不得使用“本文/文章/该页面/本页面/网页”等元信息表述；不得出现“综上/我们认为/模型判断”等主观或流程性语言。
- 若页面主要为行情/模板/数据页，缺少新闻事实，请直接生成基于数值的“数据分析式摘要”（例如概括指数涨跌、涨跌幅、成交额/量、资金流向、ETF/板块表现等），切勿返回“无实质新闻”。
- 只输出 JSON。
"""
    
    async def news(self, title: str, content: str, url: str = None) -> Optional[NewsAnalysisResult]:
        """
        使用LLM分析新闻内容
        """
        if self.llm_service == "none":
            logging.warning("No LLM service available, using fallback analysis")
            return await self._fallback_analysis(title, content)
        
        try:
            # 准备输入
            prompt = self.analysis_prompt.format(title=title, content=content[:4000])  # 限制长度
            
            # 调用LLM
            if self.llm_service == "azure":
                # 严格按照用户要求，仅使用 Responses API，不再回退到 Chat Completions
                response = await self._call_azure_openai_responses(prompt)
            elif self.llm_service == "local":
                response = await self._call_local_llm(prompt)
            else:
                response = None
            
            if not response:
                return await self._fallback_analysis(title, content)
            
            # 解析响应
            analysis_data = self._parse_llm_response(response)
            if not analysis_data:
                return await self._fallback_analysis(title, content)
            # 归一化/清洗字段，避免 LLM 返回多余或不匹配字段导致构造失败
            try:
                analysis_data = self._normalize_analysis_dict(analysis_data)
            except Exception as _e:
                # 如果清洗仍然失败，回退到简易分析
                return await self._fallback_analysis(title, content)
            
            # 创建结果对象
            # 统一风格修正（去除“本文/该页面”等措辞；模板页归一化）
            analysis_data["summary"] = self._postprocess_summary(analysis_data.get("summary") or "", content)
            result = NewsAnalysisResult(**analysis_data)
            
            logging.info(f"LLM analysis completed for: {title[:50]}...")
            return result
            
        except Exception as e:
            logging.error(f"LLM analysis failed: {e}")
            return await self._fallback_analysis(title, content)
        

    
    # 已移除 Azure Chat Completions 相关调用，统一改为 Responses API

    async def _call_azure_openai_responses(self, prompt: str) -> Optional[str]:
        """
        新版 Responses API（/openai/responses）
        参考官方示例：
        curl -X POST "{endpoint}/openai/responses?api-version=2025-04-01-preview" \
            -H "Content-Type: application/json" \
            -H "Authorization: Bearer $AZURE_API_KEY" \
            -d '{"messages": [{"role": "user", "content": "..."}], "max_completion_tokens": 16384, "model": "gpt-5-mini"}'
        """

        try:
            # 严格遵循示例：固定使用 Authorization: Bearer，并且仅包含 user 消息
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.azure_key}"
            }


            url = f"{self.azure_endpoint}/openai/responses?api-version={self.azure_api_version}"

            # 在 Azure OpenAI 中，model 字段应传入“部署名”（如果设置了部署名）
            model_name = self.azure_deployment or self.azure_model

            # Use Responses API "input" style (OpenAI-compatible); Azure now expects `input` not `messages`
            payload: Dict[str, Any] = {
                "input": prompt,
                "max_output_tokens": max(512, min(self.azure_max_completion_tokens, 4096)),
                "model": model_name,
            }

            # Responses API now expects JSON hint under text.format, not response_format
            if getattr(self, "azure_force_json", False):
                # Some Azure deployments expect an object type for text.format
                # rather than a plain string. Use "json_object" to request structured JSON.
                payload["text"] = {"format": {"type": "json_object"}}

            # 不添加 response_format/temperature/system 等字段，确保与示例严格一致

            # 在全局冷却期间等待
            await self._respect_global_cooldown()
            # 遵守全局速率限制（5 次/分钟，或按环境变量配置）
            await self._respect_global_rate_limit()
            # 使用全局信号量限制并发
            async with LLMNewsProcessor._sem:  # type: ignore[arg-type]
                # 记录本次请求进入速率窗口
                await self._record_llm_call()
                # 初次请求
                resp = await self.http_client.post(url, headers=headers, json=payload)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as he:
                status = he.response.status_code if he.response is not None else None
                body = None
                try:
                    body = he.response.text
                except Exception:
                    body = None
                logging.error(f"Azure OpenAI Responses API call failed: HTTP {status}; body: {body}")
                # 并发/速率限制：遇到 429，进入全局冷却（默认60秒或使用 Retry-After）
                if status == 429:
                    retry_after = self._parse_retry_after_seconds(he.response)
                    await self._trigger_global_cooldown(retry_after)
                    # 再次等待冷却结束后重试一次
                    await self._respect_global_cooldown()
                    await self._respect_global_rate_limit()
                    async with LLMNewsProcessor._sem:  # type: ignore[arg-type]
                        try:
                            await self._record_llm_call()
                            resp = await self.http_client.post(url, headers=headers, json=payload)
                            resp.raise_for_status()
                        except Exception as e2:
                            logging.error(f"Azure OpenAI retry after cooldown failed: {e2}")
                            return None
                # 若是 400，尝试减少 max tokens 并重试一次，缓解部分上限类问题
                elif status == 400:
                    try:
                        # First, try a compatibility retry: remove/adjust fields the backend rejects
                        body_text = (body or "")
                        compat_retry_payload = dict(payload)
                        adjusted = False
                        # Remove JSON forcing fields if mentioned in error
                        if any(tok in body_text for tok in ["text.format", "modalities", "response_format"]):
                            for k in ["text", "response_format", "modalities"]:
                                if k in compat_retry_payload:
                                    compat_retry_payload.pop(k, None)
                                    adjusted = True
                        # Remove temperature if the model doesn't support it
                        if ("Unsupported parameter" in body_text or "Unknown parameter" in body_text) and "'temperature'" in body_text:
                            if "temperature" in compat_retry_payload:
                                compat_retry_payload.pop("temperature", None)
                                adjusted = True
                        # Swap token field name if backend expects the other variant
                        if ("Unsupported parameter" in body_text or "Unknown parameter" in body_text) and "'max_output_tokens'" in body_text:
                            val = compat_retry_payload.pop("max_output_tokens", None)
                            if val is not None:
                                compat_retry_payload["max_completion_tokens"] = val
                                adjusted = True
                        if ("Unsupported parameter" in body_text or "Unknown parameter" in body_text) and "'max_completion_tokens'" in body_text:
                            val = compat_retry_payload.pop("max_completion_tokens", None)
                            if val is not None:
                                compat_retry_payload["max_output_tokens"] = val
                                adjusted = True
                        if adjusted:
                            await self._respect_global_rate_limit()
                            async with LLMNewsProcessor._sem:  # type: ignore[arg-type]
                                await self._record_llm_call()
                                resp = await self.http_client.post(url, headers=headers, json=compat_retry_payload)
                                resp.raise_for_status()
                        else:
                            # Otherwise, try reducing tokens and retry once
                            current_tokens = payload.get("max_output_tokens") or payload.get("max_completion_tokens") or 2048
                            smaller = max(256, min(1024, int(current_tokens / 2)))
                            retry_payload = dict(payload)
                            if "max_output_tokens" in retry_payload:
                                retry_payload["max_output_tokens"] = smaller
                            elif "max_completion_tokens" in retry_payload:
                                retry_payload["max_completion_tokens"] = smaller
                            await self._respect_global_rate_limit()
                            async with LLMNewsProcessor._sem:  # type: ignore[arg-type]
                                await self._record_llm_call()
                                resp = await self.http_client.post(url, headers=headers, json=retry_payload)
                                resp.raise_for_status()
                    except Exception as e2:
                        logging.error(f"Azure OpenAI retry failed: {e2}")
                        return None
                else:
                    return None

            try:
                data = resp.json()
            except Exception:
                body_text = await resp.aread() if hasattr(resp, "aread") else resp.text
                logging.error(f"Azure Responses API returned non-JSON body: {body_text}")
                data = {}

            text = None

            # Quick wins: common top-level shortcuts
            for key in ("content", "text", "output_text", "output_text_display"):
                val = data.get(key)
                if isinstance(val, str) and val.strip():
                    text = val
                    break

            # Inspect 'output' / 'outputs' list (preferred Responses API structure)
            if not text:
                outputs = data.get("output") or data.get("outputs")
                if isinstance(outputs, list):
                    parts: List[str] = []
                    for out in outputs:
                        if not isinstance(out, dict):
                            continue

                        # Some entries are of type 'message' and contain a 'content' list
                        content_list = out.get("content") or out.get("contents")
                        if isinstance(content_list, list):
                            for c in content_list:
                                if isinstance(c, dict):
                                    # typical payload element has type 'output_text' and 'text'
                                    t = c.get("text") or c.get("content") or c.get("output_text")
                                    if isinstance(t, str) and t.strip():
                                        parts.append(t)
                        # fallback: some outputs put text at the top level of the entry
                        top_text = out.get("text") or out.get("output_text")
                        if isinstance(top_text, str) and top_text.strip():
                            parts.append(top_text)

                    if parts:
                        # join multiple parts into a single text blob
                        text = "\n".join(parts)

            # Extra fallback: older/alternate format choices -> message -> content -> text
            if not text:
                try:
                    outputs = data.get("output") or data.get("outputs") or data.get("choices")
                    if isinstance(outputs, list) and outputs:
                        first = outputs[0]
                        if isinstance(first, dict):
                            # nested assistant/message structure
                            content = first.get("content") or first.get("message") or first.get("message", {}).get("content")
                            if isinstance(content, list):
                                for c in content:
                                    if isinstance(c, dict) and c.get("text"):
                                        text = c.get("text")
                                        break
                            elif isinstance(content, dict) and content.get("text"):
                                text = content.get("text")
                except Exception:
                    text = None

            # Ensure we at least set text to empty string if nothing found (caller expects str or None)
            if text is None:
                text = None

            if isinstance(text, str) and text.strip():
                return text

            # 兼容解析 output -> message -> content -> text
            try:
                outputs = data.get("output") or data.get("outputs")
                if isinstance(outputs, list) and outputs:
                    first = outputs[0]
                    if isinstance(first, dict):
                        content = first.get("content")
                        if isinstance(content, list) and content:
                            # 找到第一个包含 text 的元素
                            for c in content:
                                if isinstance(c, dict) and c.get("text"):
                                    return c.get("text")
            except Exception:
                pass

            # 再兼容 chat choices（极少数代理层会返回旧格式）
            try:
                return data.get("choices", [{}])[0].get("message", {}).get("content")
            except Exception:
                return None

        except Exception as e:
            logging.error(f"Azure OpenAI Responses API call failed: {e}")
            return None

    def _parse_retry_after_seconds(self, response: Optional[httpx.Response]) -> float:
        """解析 Retry-After 或 x-ms-* 速率限制 header，默认返回冷却秒数。"""
        if response is None:
            return self._cooldown_default
        try:
            # Standard Retry-After (seconds)
            ra = response.headers.get("Retry-After")
            if ra:
                try:
                    return float(ra)
                except Exception:
                    pass
            # Azure sometimes returns retry-after-ms
            ra_ms = response.headers.get("retry-after-ms") or response.headers.get("x-ms-retry-after-ms")
            if ra_ms:
                try:
                    return max(self._cooldown_default, float(ra_ms) / 1000.0)
                except Exception:
                    pass
        except Exception:
            pass
        return self._cooldown_default

    async def _trigger_global_cooldown(self, seconds: float) -> None:
        """设置全局冷却窗口。"""
        try:
            async with LLMNewsProcessor._cooldown_lock:  # type: ignore[arg-type]
                LLMNewsProcessor._cooldown_until = max(LLMNewsProcessor._cooldown_until, time.time() + seconds)
        except Exception:
            # Fallback: sleep locally if lock unavailable
            await asyncio.sleep(seconds)

    async def _respect_global_cooldown(self) -> None:
        """等待当前全局冷却窗口结束。"""
        while True:
            try:
                async with LLMNewsProcessor._cooldown_lock:  # type: ignore[arg-type]
                    remaining = LLMNewsProcessor._cooldown_until - time.time()
            except Exception:
                remaining = 0
            if remaining <= 0:
                return
            # 睡眠小片段，避免长时间阻塞无法响应取消
            await asyncio.sleep(min(remaining, 5.0))

    async def _respect_global_rate_limit(self) -> None:
        """在任意 60s 窗口内限制调用次数（默认 5/分钟，可通过 AZURE_OPENAI_RATE_LIMIT_PER_MINUTE 配置）。"""
        window = LLMNewsProcessor._rate_window_seconds
        try:
            limit = int(LLMNewsProcessor._rate_limit_per_window)
        except Exception:
            limit = 5
        limit = max(1, limit)
        while True:
            now = time.time()
            try:
                async with LLMNewsProcessor._rate_lock:  # type: ignore[arg-type]
                    cutoff = now - window
                    LLMNewsProcessor._call_timestamps = [t for t in LLMNewsProcessor._call_timestamps if t >= cutoff]
                    if len(LLMNewsProcessor._call_timestamps) < limit:
                        return
                    earliest = min(LLMNewsProcessor._call_timestamps) if LLMNewsProcessor._call_timestamps else now
                    wait = max(0.05, earliest + window - now)
            except Exception:
                wait = 1.0
            await asyncio.sleep(min(wait, 5.0))

    async def _record_llm_call(self) -> None:
        """记录一次调用时间用于速率限制。"""
        try:
            async with LLMNewsProcessor._rate_lock:  # type: ignore[arg-type]
                LLMNewsProcessor._call_timestamps.append(time.time())
        except Exception:
            pass
    
    # 已移除 OpenAI 直连路径，统一只走 Azure Responses API 或本地 LLM（如配置）
    
    async def _call_local_llm(self, prompt: str) -> Optional[str]:
        """
        调用本地LLM API
        """
        try:
            payload = {
                "prompt": prompt,
                "max_tokens": 2000,
                "temperature": 0.1
            }
            
            response = await self.http_client.post(f"{self.local_llm_url}/generate", json=payload)
            response.raise_for_status()
            
            data = response.json()
            return data.get("response", "")
            
        except Exception as e:
            logging.error(f"Local LLM API call failed: {e}")
            return None
    
    def _parse_llm_response(self, response: str) -> Optional[Dict[str, Any]]:
        """
        解析LLM响应
        """
        try:
            # 尝试直接解析JSON
            if response.strip().startswith('{'):
                data = json.loads(response)
                # 兼容嵌套返回 {"analysis_result": {...}}
                if isinstance(data, dict) and isinstance(data.get("analysis_result"), dict):
                    return data.get("analysis_result")
                return data
            
            # 尝试提取JSON块
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(1))
                if isinstance(data, dict) and isinstance(data.get("analysis_result"), dict):
                    return data.get("analysis_result")
                return data
            
            # 尝试查找JSON对象
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                if isinstance(data, dict) and isinstance(data.get("analysis_result"), dict):
                    return data.get("analysis_result")
                return data
            
            logging.warning(f"Could not parse LLM response as JSON: {response[:200]}...")
            return None
            
        except json.JSONDecodeError as e:
            logging.error(f"JSON parsing failed: {e}")
            return None

    def _normalize_analysis_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        将 LLM 返回的字典归一化为 NewsAnalysisResult 需要的字段与类型。
        - 过滤未知字段
        - 为缺失字段填默认值
        - 修正常见类型偏差（数字字符串→float，单值→列表，None→默认）
        """
        if not isinstance(data, dict):
            return {}

        def to_list(val: Any) -> List[Any]:
            if val is None:
                return []
            if isinstance(val, list):
                return val
            return [val]

        def to_float(val: Any, default: float = 0.0) -> float:
            try:
                if isinstance(val, (int, float)):
                    return float(val)
                if isinstance(val, str):
                    # 去掉可能的百分号
                    s = val.strip().replace('%', '')
                    return float(s)
            except Exception:
                return default
            return default

        # 兼容一些别名字段
        aliases = {
            "topics": "main_topics",
            "entities": None,  # 忽略顶层 entities（我们只消费扁平字段）
            "analysis_result": None,  # 已在解析时处理
        }
        for k, v in list(data.items()):
            if k in aliases and aliases[k]:
                data[aliases[k]] = v
            if k in aliases and aliases[k] is None:
                # 删除未使用的别名容器
                data.pop(k, None)

        # financial_metrics 结构修正
        fm = data.get("financial_metrics")
        if not isinstance(fm, dict):
            fm = {}
        fm.setdefault("mentioned_values", to_list(fm.get("mentioned_values")))
        fm.setdefault("percentages", to_list(fm.get("percentages")))
        fm.setdefault("financial_terms", to_list(fm.get("financial_terms")))

        normalized: Dict[str, Any] = {
            "summary": data.get("summary") or "",
            "category": data.get("category") or NewsCategory.FINANCE.value,
            "companies": to_list(data.get("companies")),
            "people": to_list(data.get("people")),
            "locations": to_list(data.get("locations")),
            "stock_symbols": to_list(data.get("stock_symbols")),
            "sentiment_type": data.get("sentiment_type") or SentimentType.NEUTRAL.value,
            "sentiment_score": to_float(data.get("sentiment_score"), 0.0),
            "sentiment_confidence": to_float(data.get("sentiment_confidence"), 0.5),
            "main_topics": to_list(data.get("main_topics")),
            "keywords": to_list(data.get("keywords")),
            "financial_metrics": fm,
            "market_impact": data.get("market_impact") or "low",
            "relevance_score": to_float(data.get("relevance_score"), 0.5),
            "time_references": to_list(data.get("time_references")),
            "content_quality": to_float(data.get("content_quality"), 0.5),
            "reliability_assessment": data.get("reliability_assessment") or "medium",
        }
        return normalized
    
    async def _fallback_analysis(self, title: str, content: str) -> NewsAnalysisResult:
        """
        备用分析方法（不使用LLM）
        """
        # 基本文本分析
        summary = self._generate_simple_summary(content)
        category = self._classify_category(title, content)
        
        # 实体提取
        companies = self._extract_companies(title + " " + content)
        stock_symbols = self._extract_stock_symbols(title + " " + content)
        
        # 简单情感分析
        sentiment_result = self._simple_sentiment_analysis(title, content)
        
        # 关键词提取
        keywords = self._extract_keywords(title, content)
        
        # 财经指标
        financial_metrics = self._extract_financial_metrics(content)
        
        res = NewsAnalysisResult(
            summary=summary,
            category=category,
            companies=companies,
            people=[],  # 简单实现中不提取人物
            locations=[],  # 简单实现中不提取地点
            stock_symbols=stock_symbols,
            sentiment_type=sentiment_result["type"],
            sentiment_score=sentiment_result["score"],
            sentiment_confidence=sentiment_result["confidence"],
            main_topics=keywords[:3],  # 使用前3个关键词作为主题
            keywords=keywords,
            financial_metrics=financial_metrics,
            market_impact=self._assess_market_impact(title, content),
            relevance_score=self._calculate_relevance_score(title, content),
            time_references=self._extract_time_references(content),
            content_quality=self._assess_content_quality(title, content),
            reliability_assessment="medium"  # 默认中等可靠性
        )
        # 回退路径也做摘要风格修正
        res.summary = self._postprocess_summary(res.summary, content)
        return res

    def _postprocess_summary(self, summary: str, content: str) -> str:
        """将 LLM 或回退生成的摘要规范为“新闻纪要”口吻。

        - 移除“本文/文章/本页面/该页面/网页/本报告”等措辞
        - 移除“我们/模型/认为/综上”等方法或主观描述
        - 对明显的模板/行情页面，生成基于数值的“数据分析式摘要”
        """
        s = (summary or "").strip()
        if not s:
            return s
        # 模板/占位符判定（基于内容）：大量占位符、指标串或“行情/数据中心/技术指标”等字样
        lowered = (content or "").lower()
        template_markers = ["@open@", "@volume@", "macd", "kdj", "boll", "数据展示", "技术指标", "行情"]
        if any(m in lowered for m in template_markers) and len(re.findall(r"@\w+@", content or "")) >= 2:
            return self._compose_market_data_summary(content)
        # 去元信息化措辞
        s = re.sub(r"\b(本文|本页面|该页面|网页|文章)\b", "", s)
        s = re.sub(r"\b(我们|模型|认为|综上|总的来看|总体而言)\b", "", s)
        # 清理多余空格与标点
        s = re.sub(r"\s+", " ", s).strip()
        s = re.sub(r"[。]{2,}", "。", s)
        # 控制长度
        if len(s) > 140:
            s = s[:140].rstrip() + "…"
        return s

    def _compose_market_data_summary(self, content: str) -> str:
        """当页面为行情/模板/数据页时，基于可见参数生成“数据分析式摘要”。

        逻辑：
        - 提取常见指数的涨跌幅（上证/深成/创业板/沪深300/中证500/中证1000/上证50）
        - 提取成交额/成交量
        - 提取北向/南向资金净流入/净流出
        - 提取若干板块/ETF表现
        - 组合为 50-140 字的客观一句话摘要
        """
        text = content or ""
        # 指数涨跌幅
        index_pattern = re.compile(r"(上证指数|沪指|上证综指|深证成指|深成指|创业板指|创业板|沪深300|中证500|中证1000|上证50)[^%\n\r]{0,20}?([+-]?\d+(?:\.\d+)?%)")
        idx_moves: List[Tuple[str, str]] = []
        for m in index_pattern.finditer(text):
            name = m.group(1)
            pct = m.group(2)
            # 规范化简称
            short = {
                "上证指数": "上证",
                "沪指": "上证",
                "上证综指": "上证",
                "深证成指": "深成",
                "深成指": "深成",
                "创业板指": "创业板",
                "创业板": "创业板",
                "沪深300": "沪深300",
                "中证500": "中证500",
                "中证1000": "中证1000",
                "上证50": "上证50",
            }.get(name, name)
            pair = (short, pct)
            if pair not in idx_moves:
                idx_moves.append(pair)
        # 成交额/量
        turnover = None
        m_turnover = re.search(r"成交额[：: ]?([\d\.]+)(万|亿)?元?", text)
        if m_turnover:
            turnover = f"成交额约{m_turnover.group(1)}{m_turnover.group(2) or ''}元"
        volume = None
        m_volume = re.search(r"成交量[：: ]?([\d\.]+)(万手|亿手|万股|亿股)?", text)
        if m_volume:
            volume = f"成交量{m_volume.group(1)}{m_volume.group(2) or ''}"
        # 资金流向
        funds = None
        m_north = re.search(r"(北向资金|南向资金)[^\d]{0,8}净(流入|流出)[：: ]?([\d\.]+)(万|亿)?元?", text)
        if m_north:
            funds = f"{m_north.group(1)}净{m_north.group(2)}约{m_north.group(3)}{m_north.group(4) or ''}元"
        # 板块/ETF表现（简单关键词）
        sectors = []
        sector_names = ["半导体", "新能源", "有色", "煤炭", "锂电", "券商", "银行", "地产", "医药", "白酒", "军工", "汽车", "光伏", "TMT", "消费"]
        for name in sector_names:
            if re.search(fr"{name}.{{0,6}}(领涨|领跌|涨幅居前|跌幅居前)", text):
                sectors.append(name)
            if len(sectors) >= 2:
                break
        # 组装
        parts: List[str] = []
        if idx_moves:
            top = [f"{n}{p}" for n, p in idx_moves[:3]]
            parts.append("主要指数：" + "、".join(top))
        if turnover:
            parts.append(turnover)
        if volume:
            parts.append(volume)
        if funds:
            parts.append(funds)
        if sectors:
            parts.append("板块：" + "、".join(sectors))
        if not parts:
            return "数据速览：未能提取关键行情参数。"
        s = "；".join(parts) + "。"
        # 长度控制与清理
        s = re.sub(r"\s+", " ", s).strip()
        if len(s) > 140:
            s = s[:140].rstrip("；。 ") + "…"
        return s
    
    def _generate_simple_summary(self, content: str, max_length: int = 150) -> str:
        """
        生成简单摘要
        """
        if not content:
            return ""
        
        # 简单的摘要生成：取前面的句子
        sentences = re.split(r'[。！？.!?]', content)
        summary = ""
        
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) > 10:  # 过滤太短的句子
                if len(summary + sentence) < max_length:
                    summary += sentence + "。"
                else:
                    break
        
        return summary.strip()
    
    def _classify_category(self, title: str, content: str) -> str:
        """
        分类新闻类别
        """
        text = (title + " " + content).lower()
        
        # 关键词映射
        category_keywords = {
            NewsCategory.POLICY.value: ["政策", "监管", "法规", "政府", "央行", "证监会"],
            NewsCategory.COMPANY.value: ["公司", "企业", "股价", "财报", "业绩", "营收"],
            NewsCategory.INDUSTRY.value: ["行业", "板块", "产业", "领域"],
            NewsCategory.MARKET.value: ["市场", "指数", "大盘", "交易"],
            NewsCategory.ECONOMIC.value: ["经济", "GDP", "通胀", "就业"]
        }
        
        for category, keywords in category_keywords.items():
            if any(keyword in text for keyword in keywords):
                return category
        
        return NewsCategory.FINANCE.value  # 默认分类
    
    def _extract_companies(self, text: str) -> List[str]:
        """
        提取公司名称
        """
        # 简单的公司名称模式
        company_pattern = r'[^，。！？\s]{2,10}(?:股份有限公司|有限公司|集团|控股|科技|传媒|医药|银行|保险|证券)'
        companies = re.findall(company_pattern, text)
        
        # 去重并过滤
        unique_companies = list(set(companies))
        return unique_companies[:10]  # 限制数量
    
    def _extract_stock_symbols(self, text: str) -> List[str]:
        """
        提取股票代码
        """
        # 股票代码模式
        stock_pattern = r'\b\d{6}(?:\.[A-Z]{2})?\b'
        symbols = re.findall(stock_pattern, text)
        
        return list(set(symbols))
    
    def _simple_sentiment_analysis(self, title: str, content: str) -> Dict[str, Any]:
        """
        简单情感分析
        """
        text = (title + " " + content).lower()
        
        # 正面词汇
        positive_words = ["上涨", "增长", "盈利", "突破", "利好", "买入", "推荐", "看好", "乐观"]
        # 负面词汇
        negative_words = ["下跌", "亏损", "下滑", "利空", "卖出", "风险", "担心", "悲观", "暴跌"]
        
        positive_count = sum(1 for word in positive_words if word in text)
        negative_count = sum(1 for word in negative_words if word in text)
        
        total_count = positive_count + negative_count
        
        if total_count == 0:
            return {
                "type": SentimentType.NEUTRAL.value,
                "score": 0.0,
                "confidence": 0.5
            }
        
        if positive_count > negative_count:
            score = positive_count / total_count
            return {
                "type": SentimentType.POSITIVE.value,
                "score": score,
                "confidence": min(score + 0.3, 1.0)
            }
        elif negative_count > positive_count:
            score = -(negative_count / total_count)
            return {
                "type": SentimentType.NEGATIVE.value,
                "score": score,
                "confidence": min(abs(score) + 0.3, 1.0)
            }
        else:
            return {
                "type": SentimentType.NEUTRAL.value,
                "score": 0.0,
                "confidence": 0.6
            }
    
    def _extract_keywords(self, title: str, content: str) -> List[str]:
        """
        提取关键词
        """
        text = title + " " + content
        
        # 财经关键词
        financial_terms = [
            "股价", "涨幅", "跌幅", "成交量", "市值", "营收", "利润",
            "财报", "业绩", "增长", "下滑", "投资", "融资", "IPO",
            "重组", "并购", "分红", "股息", "估值", "PE", "PB"
        ]
        
        keywords = []
        for term in financial_terms:
            if term in text:
                keywords.append(term)
        
        return keywords[:15]  # 限制关键词数量
    
    def _extract_financial_metrics(self, content: str) -> Dict[str, Any]:
        """
        提取财经指标
        """
        # 提取数值和百分比
        values = re.findall(r'\d+(?:\.\d+)?(?:万|亿|千万)?[元块]', content)
        percentages = re.findall(r'\d+(?:\.\d+)?%', content)
        
        return {
            "mentioned_values": values[:10],
            "percentages": percentages[:10],
            "financial_terms": self._extract_keywords("", content)
        }
    
    def _assess_market_impact(self, title: str, content: str) -> str:
        """
        评估市场影响
        """
        text = (title + " " + content).lower()
        
        high_impact_words = ["重大", "突发", "紧急", "暴涨", "暴跌", "停牌", "重组"]
        medium_impact_words = ["公告", "发布", "调整", "变动"]
        
        if any(word in text for word in high_impact_words):
            return "high"
        elif any(word in text for word in medium_impact_words):
            return "medium"
        else:
            return "low"
    
    def _calculate_relevance_score(self, title: str, content: str) -> float:
        """
        计算相关性分数
        """
        score = 0.5  # 基础分数
        
        # 标题长度合理性
        if title and 10 <= len(title) <= 100:
            score += 0.1
        
        # 内容长度
        if content and len(content) >= 200:
            score += 0.2
        
        # 包含财经关键词
        financial_keywords = ["股票", "股价", "市场", "投资", "财报", "业绩"]
        text = (title + " " + content).lower()
        
        keyword_count = sum(1 for keyword in financial_keywords if keyword in text)
        score += min(keyword_count * 0.05, 0.2)
        
        return min(score, 1.0)
    
    def _extract_time_references(self, content: str) -> List[str]:
        """
        提取时间引用
        """
        time_patterns = [
            r'\d{4}年\d{1,2}月\d{1,2}日',
            r'\d{1,2}月\d{1,2}日',
            r'今日|昨日|明日',
            r'本周|上周|下周',
            r'本月|上月|下月',
            r'今年|去年|明年'
        ]
        
        time_refs = []
        for pattern in time_patterns:
            matches = re.findall(pattern, content)
            time_refs.extend(matches)
        
        return list(set(time_refs))[:10]
    
    def _assess_content_quality(self, title: str, content: str) -> float:
        """
        评估内容质量
        """
        score = 0.5  # 基础分数
        
        # 标题存在且合理
        if title and 10 <= len(title) <= 100:
            score += 0.15
        
        # 内容长度适中
        if content:
            content_length = len(content)
            if content_length >= 500:
                score += 0.2
            elif content_length >= 200:
                score += 0.1
        
        # 段落结构
        if content and '\n' in content:
            paragraphs = content.split('\n')
            if len(paragraphs) >= 3:
                score += 0.1
        
        # 包含数字和数据
        if content and re.search(r'\d+(?:\.\d+)?(?:%|万|亿)', content):
            score += 0.05
        
        return min(score, 1.0)
    
    async def batch_analyze_news(self, articles: List[Dict[str, Any]]) -> List[Optional[NewsAnalysisResult]]:
        """
        批量分析新闻
        """
        results = []
        
        for article in articles:
            title = article.get('title', '')
            content = article.get('content', '')
            url = article.get('url', '')
            
            result = await self.analyze_news(title, content, url)
            results.append(result)
            
            # 添加延迟以避免API限制
            await asyncio.sleep(0.5)
        
        return results
    
    def to_dict(self, result: NewsAnalysisResult) -> Dict[str, Any]:
        """
        将分析结果转换为字典
        """
        return asdict(result)

    # Alias for backward compatibility
    async def analyze_news(self, title: str, content: str, url: str = None) -> Optional[NewsAnalysisResult]:
        """Alias for news() method for backward compatibility."""
        return await self.news(title, content, url)
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        if self.http_client:
            await self.http_client.aclose()