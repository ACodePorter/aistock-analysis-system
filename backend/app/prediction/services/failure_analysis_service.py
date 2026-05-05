"""预测失败归因兼容层。

当前版本基于已评估的偏差样本生成规则型归因，不调用 LLM、不自动修改模型，
为后续 Agent 受控迭代和自动门禁提供稳定契约。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


DISCLAIMER = "失败归因用于复盘模型表现和数据覆盖，不构成投资建议，也不会自动调整生产模型。"


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _pct(value: Optional[float]) -> Optional[float]:
    return round(value, 2) if value is not None else None


def _root_cause(code: str, label: str, severity: str, evidence: str, recommendation: str, count: int) -> dict:
    return {
        "code": code,
        "label": label,
        "severity": severity,
        "evidence": evidence,
        "recommendation": recommendation,
        "sample_count": count,
    }


def build_failure_analysis(
    symbol: str,
    deviation_cases: list[dict],
    *,
    quality: Optional[dict] = None,
    feature_snapshot: Optional[dict] = None,
) -> dict:
    """从偏差样本生成可展示、可自动核实的失败归因摘要。"""
    cases = [case for case in (deviation_cases or []) if _to_float(case.get("error_pct")) is not None]
    high_cases = [case for case in cases if case.get("deviation_level") in {"high", "critical"}]
    direction_misses = [case for case in cases if case.get("direction_correct") is False]
    interval_misses = [case for case in cases if case.get("interval_hit") is False]
    signed_errors = [_to_float(case.get("signed_error_pct")) for case in cases]
    signed_errors = [err for err in signed_errors if err is not None]
    avg_signed_bias = round(sum(signed_errors) / len(signed_errors), 2) if signed_errors else None
    avg_error = round(sum(float(case.get("error_pct") or 0) for case in cases) / len(cases), 2) if cases else None

    root_causes = []
    if direction_misses:
        root_causes.append(_root_cause(
            "direction_miss",
            "方向判断未命中",
            "high" if len(direction_misses) >= 2 else "medium",
            f"近窗 {len(direction_misses)} 个样本方向未命中。",
            "优先复盘预测日前后的新闻、资金流和市场状态，降低单一方向概率的权重依赖。",
            len(direction_misses),
        ))
    if high_cases:
        root_causes.append(_root_cause(
            "large_price_error",
            "价格偏差偏大",
            "high",
            f"近窗 {len(high_cases)} 个样本达到高偏差或严重偏差。",
            "检查置信区间、波动率估计和异常行情样本，必要时降低该股短期预测权重。",
            len(high_cases),
        ))
    if interval_misses:
        root_causes.append(_root_cause(
            "interval_miss",
            "置信区间未覆盖实际收盘",
            "medium",
            f"{len(interval_misses)} 个样本落在预测区间外。",
            "复核区间宽度是否低估波动，尤其关注涨跌停、跳空和成交量突变。",
            len(interval_misses),
        ))
    if avg_signed_bias is not None and abs(avg_signed_bias) >= 1.5:
        direction = "高估" if avg_signed_bias > 0 else "低估"
        root_causes.append(_root_cause(
            "systematic_bias",
            f"系统性{direction}",
            "medium",
            f"近窗平均有符号偏差 {avg_signed_bias:+.2f}%。",
            "在回测中检查近期行情 regime 是否变化，并观察模型是否持续同向偏差。",
            len(cases),
        ))

    coverage_notes = []
    if feature_snapshot:
        completeness = _to_float(feature_snapshot.get("completeness_score"))
        if completeness is not None and completeness < 80:
            coverage_notes.append(f"特征快照覆盖率 {completeness:.1f}%，复盘证据不完整。")
        counts = feature_snapshot.get("factor_counts") or {}
        if int(counts.get("news_articles") or 0) == 0:
            coverage_notes.append("预测窗口缺少关联新闻，事件驱动归因可信度较低。")
        if int(counts.get("market_breadth_total") or 0) == 0:
            coverage_notes.append("缺少市场广度数据，无法完整解释市场环境。")

    if not root_causes and cases:
        root_causes.append(_root_cause(
            "minor_noise",
            "偏差处于可观察区间",
            "low",
            "当前样本未触发明显高风险归因。",
            "继续累积样本，观察方向命中率和偏差是否恶化。",
            len(cases),
        ))

    if not cases:
        headline = "暂无可归因的已评估偏差样本。"
        next_actions = ["等待目标日实际收盘回填后再生成失败归因。"]
        severity = "unknown"
    else:
        severity = "high" if any(cause["severity"] == "high" for cause in root_causes) else "medium" if any(cause["severity"] == "medium" for cause in root_causes) else "low"
        headline = f"已复盘 {len(cases)} 个偏差样本，识别 {len(root_causes)} 类主要归因。"
        if high_cases:
            headline = f"近窗存在 {len(high_cases)} 个高偏差样本，建议优先进入自动核实与受控复盘。"
        next_actions = [cause["recommendation"] for cause in root_causes[:3]]
        if coverage_notes:
            next_actions.append("补齐缺失因子后再决定是否调整模型或阈值。")

    return {
        "symbol": symbol,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "severity": severity,
        "headline": headline,
        "sample_count": len(cases),
        "high_deviation_count": len(high_cases),
        "direction_miss_count": len(direction_misses),
        "interval_miss_count": len(interval_misses),
        "avg_error_pct": _pct(avg_error),
        "avg_signed_bias_pct": _pct(avg_signed_bias),
        "root_causes": root_causes[:5],
        "coverage_notes": coverage_notes[:4],
        "next_actions": next_actions[:4],
        "quality_snapshot": {
            "quality_grade": (quality or {}).get("quality_grade"),
            "quality_score": (quality or {}).get("quality_score"),
            "confidence_level": (quality or {}).get("confidence_level"),
        },
        "disclaimer": DISCLAIMER,
    }