
"""
模块说明
---------
本模块用于基于价格、信号和预测数据生成简明的股票技术分析报告，并可选调用 Azure OpenAI Responses API 对文本摘要进行口语化精简。
设计目标是：
- 提取并规范化不同来源的行情/信号/预测输入；
- 计算简单的数据质量和置信度指标；
- 生成结构化的报告数据（字典格式）和可读的文本摘要；
- 在配置了 Azure OpenAI Key 时，异步调用云端 LLM 对摘要进行简化（非必须）。
环境变量（可选）
- AZURE_OPENAI_KEY: 若设置则启用 llm_summarize，值为 Azure OpenAI 的 API Key。
- AZURE_OPENAI_ENDPOINT: Azure Responses API 的 endpoint（例如 https://xxxxx.openai.azure.com）。
- AZURE_OPENAI_API_VERSION: Requests API 版本，默认 "2025-04-01-preview"。
- AZURE_OPENAI_DEPLOYMENT / AZURE_OPENAI_MODEL: 优先使用部署名，否则可指定模型名（默认 "gpt-5-mini"）。
- AZURE_OPENAI_MAX_COMPLETION_TOKENS: 响应最大 token 数，默认 1024。
- AZURE_OPENAI_TIMEOUT: HTTP 请求超时（秒），默认 30。
依赖
- pandas: 用于接收和处理 DataFrame 输入。
- requests: 仅当启用 LLM 时用于 HTTP 请求（在 llm_summarize 内部按需导入）。
主要函数（摘要）
- plain_summary(symbol, name, today_row, signal_row, preds) -> str
    生成一个面向普通用户的中文纯文本技术分析要点（无 LLM 调用）。
    参数：
        - symbol (str)：股票代码。
        - name (str|None)：股票简称，可为空。
        - today_row (pd.Series)：包含当日行情至少包含 "close" 字段，建议也包含 "pct_chg"。
        - signal_row (pd.Series)：包含信号相关字段，可为空；常见字段："action","signal_score","ma_s","ma_l","rsi"。
        - preds (list[tuple[date,float,float,float]])：可选的预测列表，元素通常为 (date, pred, lower, upper)。
    返回：
        - str：多行要点字符串（中文），保留关键数字与建议。
- async llm_summarize(text) -> str
    异步将传入文本发送到 Azure Responses API 请求更口语化、面向普通投资者的简明解读（控制长度、避免夸大）。
    行为：
        - 若未设置 AZURE_OPENAI_KEY，则直接返回原文本。
        - 在请求失败或解析响应结构不符合预期时，返回原文本并在控制台打印少量错误信息以便诊断。
        - 在解析响应时兼容多种返回结构（output_text / outputs[].content[].text / choices[...]）。
    注意：
        - 需要网络访问且可能产生费用；为安全起见不要在生产日志中写入敏感 API Key。
- generate_report_data(symbol, price_data=None, signal_data=None, forecast_data=None) -> dict
    构造结构化报告字典，适合序列化（JSON）或作为 API 响应内容。
    参数：
        - symbol (str)：股票代码。
        - price_data (pd.DataFrame|None)：行情表（建议包含 trade_date, close, open, high, low, vol, pct_chg）。
        - signal_data (pd.DataFrame|None)：信号表（建议包含 trade_date, action, signal_score, ma_short, ma_long, rsi, macd）。
        - forecast_data (dict|iterable|None)：若为字典且含 "predictions" 键，则按原样嵌入；若为可迭代序列（tuple/list），则按索引解析为逐日预测。
    返回值字典（主要字段）：
        - symbol (str)
        - generated_at (ISO datetime str)
        - data_quality_score (float)：简单评分，基于 price_data 长度（>=250 -> 1.0, >=100 -> 0.8, >=50 -> 0.6, 否则 0.4）。
        - prediction_confidence (float)：若 forecast_data 提供 confidence 则使用，否则默认 0.5。
        - analysis_summary (str)：基于最新价格、信号和预测拼接的简短中文摘要，供快速展示。
        - latest_price_data (dict，可选)：包含 close/open/high/low/volume/pct_change/trade_date（ISO 字符串）。
        - signal_data (dict，可选)：包含 action/signal_score/ma_short/ma_long/rsi/macd/trade_date。
        - forecast_data (dict，可选)：规范化后的 predictions 列表及 method/confidence 等。
    行为与容错：
        - 对传入 DataFrame 做非空检查，并尝试按 trade_date 排序取最后一行作为“最新”记录。
        - 对缺失字段做安全降级（如 vol 或 pct_chg 为空则返回 None）。
        - 对 forecast_data 支持两种形态：已结构化字典或序列化的预测点列表（tuple/list）。
        - 若函数内部出现异常，会捕获并返回包含 error 字段和错误描述的字典，确保调用方得到可解析的输出。
示例（伪代码）
- 生成简要文本：
        txt = plain_summary(symbol, name, today_row, signal_row, preds)
- 使用 LLM 优化文本（异步）：
        safe_txt = await llm_summarize(txt)
- 生成结构化报告：
        report = generate_report_data(symbol, price_df, signal_df, forecast_list)
注意事项
- 本模块并非投资建议工具。分析/预测仅供参考，使用者应自行承担投资决策风险。
- 当启用 LLM 功能时，请确保遵守相应服务条款并妥善管理凭据与费用。

"""

import os
from datetime import date
import pandas as pd

USE_LLM = bool(os.getenv("AZURE_OPENAI_KEY", ""))

def plain_summary(
    symbol: str,
    name: str | None,
    today_row: pd.Series,
    signal_row: pd.Series,
    preds: list[tuple[date, float, float, float]]
) -> str:
    n = name or symbol
    action = signal_row.get("action", "HOLD") if signal_row is not None else "HOLD"
    score = float(signal_row.get("signal_score", 0) or 0) if signal_row is not None else 0
    ma_s = float(signal_row.get("ma_s", 0) or 0) if signal_row is not None else 0
    ma_l = float(signal_row.get("ma_l", 0) or 0) if signal_row is not None else 0
    rsi = float(signal_row.get("rsi", 50) or 50) if signal_row is not None else 50
    close = float(today_row["close"])
    pct = float(today_row.get("pct_chg", 0) or 0)

    bullets = [
        f"【{n}】收盘 {close:.2f}（{pct:+.2f}%），短均线 {ma_s:.2f}，长均线 {ma_l:.2f}，RSI {rsi:.1f}。",
        f"综合打分 {score:+.1f} → 建议：{action}（仅供参考）。",
    ]
    if preds:
        t0, p0, lo0, hi0 = preds[0]
        bullets.append(
            f"未来{len(preds)}天预测：第1天 {p0:.2f}（{lo0:.2f}~{hi0:.2f}）。"
        )
    return "\n".join(bullets)

async def llm_summarize(text: str) -> str:
    if not USE_LLM:
        return text
    try:
        import json
        import requests
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        api_key = os.getenv("AZURE_OPENAI_KEY")
        api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2025-04-01-preview")
        # Prefer Azure deployment name for model
        model = os.getenv("AZURE_OPENAI_DEPLOYMENT") or os.getenv("AZURE_OPENAI_MODEL", "gpt-5-mini")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            # Responses API: prefer OpenAI-compatible "input" shape
            "input": "把下面的股市技术分析摘要转成口语化、给普通投资者看的简明解读，保留关键数字，控制在150字以内，避免夸大。\n\n" + text,
            "max_output_tokens": int(os.getenv("AZURE_OPENAI_MAX_COMPLETION_TOKENS", "1024")),
            "model": model,
        }
        url = f"{endpoint}/openai/responses?api-version={api_version}"
        r = requests.post(
            url,
            headers=headers,
            data=json.dumps(payload),
            timeout=int(os.getenv("AZURE_OPENAI_TIMEOUT", "30")),
        )
        try:
            r.raise_for_status()
        except Exception:
            # Log response body for 4xx diagnostics; return original text on failure
            try:
                body = r.text
            except Exception:
                body = "(no body)"
            print(f"Azure Responses API error: HTTP {r.status_code}; body: {body}")
            return text
        data = r.json()
        # 优先使用 output_text
        txt = data.get("output_text")
        if isinstance(txt, str) and txt.strip():
            return txt.strip()
        # 兼容解析 outputs[].content[].text
        outputs = data.get("output") or data.get("outputs")
        if isinstance(outputs, list) and outputs:
            first = outputs[0]
            if isinstance(first, dict):
                content = first.get("content")
                if isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("text"):
                            return str(c.get("text")).strip()
        # 最后兼容 choices
        return data.get("choices", [{}])[0].get("message", {}).get("content", text).strip()
    except Exception:
        return text


def generate_report_data(symbol: str, price_data=None, signal_data=None, forecast_data=None):
    """
    生成报告数据
    
    Args:
        symbol: 股票代码
        price_data: 价格数据
        signal_data: 信号数据
        forecast_data: 预测数据
    
    Returns:
        dict: 报告数据
    """
    import json
    from datetime import datetime
    
    try:
        report = {
            "symbol": symbol,
            "generated_at": datetime.now().isoformat(),
            "data_quality_score": 0.0,
            "prediction_confidence": 0.0,
            "analysis_summary": ""
        }
        
        # 处理价格数据
        if price_data is not None:
            if isinstance(price_data, pd.DataFrame) and not price_data.empty:
                latest_data = price_data.sort_values("trade_date").iloc[-1]
                report["latest_price_data"] = {
                    "close": float(latest_data["close"]),
                    "open": float(latest_data["open"]) if "open" in latest_data else None,
                    "high": float(latest_data["high"]) if "high" in latest_data else None,
                    "low": float(latest_data["low"]) if "low" in latest_data else None,
                    "volume": int(latest_data["vol"]) if "vol" in latest_data and pd.notna(latest_data["vol"]) else None,
                    "pct_change": float(latest_data["pct_chg"]) if "pct_chg" in latest_data and pd.notna(latest_data["pct_chg"]) else None,
                    "trade_date": latest_data["trade_date"].isoformat() if hasattr(latest_data["trade_date"], 'isoformat') else str(latest_data["trade_date"])
                }
                
                # 计算数据质量分数
                data_points = len(price_data)
                if data_points >= 250:
                    report["data_quality_score"] = 1.0
                elif data_points >= 100:
                    report["data_quality_score"] = 0.8
                elif data_points >= 50:
                    report["data_quality_score"] = 0.6
                else:
                    report["data_quality_score"] = 0.4
        
        # 处理信号数据
        if signal_data is not None:
            if isinstance(signal_data, pd.DataFrame) and not signal_data.empty:
                latest_signal = signal_data.sort_values("trade_date").iloc[-1]
                report["signal_data"] = {
                    "action": latest_signal.get("action", "HOLD"),
                    "signal_score": float(latest_signal["signal_score"]) if "signal_score" in latest_signal and pd.notna(latest_signal["signal_score"]) else 0.0,
                    "ma_short": float(latest_signal["ma_short"]) if "ma_short" in latest_signal and pd.notna(latest_signal["ma_short"]) else None,
                    "ma_long": float(latest_signal["ma_long"]) if "ma_long" in latest_signal and pd.notna(latest_signal["ma_long"]) else None,
                    "rsi": float(latest_signal["rsi"]) if "rsi" in latest_signal and pd.notna(latest_signal["rsi"]) else None,
                    "macd": float(latest_signal["macd"]) if "macd" in latest_signal and pd.notna(latest_signal["macd"]) else None,
                    "trade_date": latest_signal["trade_date"].isoformat() if hasattr(latest_signal["trade_date"], 'isoformat') else str(latest_signal["trade_date"])
                }
        
        # 处理预测数据
        if forecast_data is not None:
            if isinstance(forecast_data, dict) and "predictions" in forecast_data:
                report["forecast_data"] = forecast_data
                report["prediction_confidence"] = forecast_data.get("confidence", 0.5)
            elif hasattr(forecast_data, '__iter__'):
                # 处理预测数组
                predictions = []
                for i, pred in enumerate(forecast_data):
                    if isinstance(pred, (list, tuple)) and len(pred) >= 3:
                        predictions.append({
                            "day": i + 1,
                            "predicted_price": float(pred[1]) if len(pred) > 1 else float(pred[0]),
                            "lower_bound": float(pred[2]) if len(pred) > 2 else None,
                            "upper_bound": float(pred[3]) if len(pred) > 3 else None
                        })
                
                report["forecast_data"] = {
                    "predictions": predictions,
                    "method": "unknown",
                    "confidence": 0.5
                }
                report["prediction_confidence"] = 0.5
        
        # 生成分析摘要
        summary_parts = []
        
        if "latest_price_data" in report:
            price_info = report["latest_price_data"]
            close = price_info["close"]
            pct_change = price_info.get("pct_change", 0) or 0
            summary_parts.append(f"股票{symbol}最新收盘价{close:.2f}，涨跌幅{pct_change:+.2f}%")
        
        if "signal_data" in report:
            signal_info = report["signal_data"]
            action = signal_info.get("action", "HOLD")
            score = signal_info.get("signal_score", 0) or 0
            summary_parts.append(f"技术指标建议{action}，综合评分{score:+.1f}")
        
        if "forecast_data" in report and report["forecast_data"].get("predictions"):
            pred = report["forecast_data"]["predictions"][0]
            summary_parts.append(f"预测明日价格{pred['predicted_price']:.2f}")
        
        report["analysis_summary"] = "；".join(summary_parts) if summary_parts else f"股票{symbol}分析报告"
        
        return report
        
    except Exception as e:
        return {
            "symbol": symbol,
            "error": f"Report generation failed: {str(e)}",
            "generated_at": datetime.now().isoformat(),
            "data_quality_score": 0.0,
            "prediction_confidence": 0.0,
            "analysis_summary": f"报告生成失败: {str(e)}"
        }
