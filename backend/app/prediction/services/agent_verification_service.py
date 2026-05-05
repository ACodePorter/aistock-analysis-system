"""Agent 输出自动核实与门禁控制。"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any, Optional


def _parse_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                return None
    return None


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


def _check_id(review_id: str, check_type: str, evidence: dict) -> str:
    raw = json.dumps({"review_id": review_id, "check_type": check_type, "evidence": evidence}, ensure_ascii=False, sort_keys=True, default=str)
    return f"vc_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:18]}"


def _check(review_id: str, check_type: str, status: str, message: str, evidence: Optional[dict] = None) -> dict:
    evidence = evidence or {}
    return {
        "check_id": _check_id(review_id, check_type, evidence),
        "review_id": review_id,
        "check_type": check_type,
        "status": status,
        "message": message,
        "evidence": evidence,
    }


def build_agent_verification(agent_review: dict, *, failure_analysis: Optional[dict] = None, feature_snapshot: Optional[dict] = None) -> dict:
    """核实 Agent 建议是否有足够证据进入受控迭代流程。"""
    failure_analysis = failure_analysis or {}
    feature_snapshot = feature_snapshot or {}
    review_id = agent_review.get("review_id") or "unknown"
    checks = []

    snapshot_id = feature_snapshot.get("snapshot_id")
    completeness = _to_float(feature_snapshot.get("completeness_score"))
    if snapshot_id:
        status = "passed" if completeness is not None and completeness >= 60 else "warning"
        checks.append(_check(
            review_id,
            "snapshot_presence",
            status,
            f"已绑定特征快照 {snapshot_id}，覆盖率 {completeness if completeness is not None else '-'}%。",
            {"snapshot_id": snapshot_id, "completeness_score": completeness},
        ))
    else:
        checks.append(_check(review_id, "snapshot_presence", "failed", "缺少特征快照，不能进入模型迭代。"))

    lineage = feature_snapshot.get("lineage") or {}
    as_of_date = _parse_date(lineage.get("as_of_date") or feature_snapshot.get("as_of_date"))
    target_date = _parse_date(lineage.get("target_date"))
    signal_date = _parse_date(lineage.get("signal_date"))
    price_date = _parse_date(lineage.get("price_trade_date"))
    if as_of_date and target_date and as_of_date <= target_date:
        checks.append(_check(review_id, "time_alignment", "passed", "预测时点早于或等于目标日，未发现时间倒挂。", {"as_of_date": as_of_date.isoformat(), "target_date": target_date.isoformat()}))
    elif as_of_date and target_date:
        checks.append(_check(review_id, "time_alignment", "failed", "预测时点晚于目标日，疑似未来函数。", {"as_of_date": as_of_date.isoformat(), "target_date": target_date.isoformat()}))
    else:
        checks.append(_check(review_id, "time_alignment", "warning", "预测时点或目标日缺失，时间对齐证据不足。"))

    if signal_date and as_of_date and signal_date <= as_of_date and (price_date is None or price_date >= as_of_date):
        checks.append(_check(review_id, "market_data_alignment", "passed", "交易信号和行情日期与预测时点可对齐。", {"signal_date": signal_date.isoformat(), "price_date": price_date.isoformat() if price_date else None}))
    else:
        checks.append(_check(review_id, "market_data_alignment", "warning", "交易信号或行情日期不完整，市场数据对齐需继续观察。", {"signal_date": signal_date.isoformat() if signal_date else None, "price_date": price_date.isoformat() if price_date else None}))

    sample_count = int(failure_analysis.get("sample_count") or 0)
    high_deviation_count = int(failure_analysis.get("high_deviation_count") or 0)
    if sample_count > 0:
        checks.append(_check(review_id, "actual_result_alignment", "passed", f"已绑定 {sample_count} 个已评估偏差样本。", {"sample_count": sample_count, "high_deviation_count": high_deviation_count}))
    else:
        checks.append(_check(review_id, "actual_result_alignment", "warning", "暂无已评估实际结果，Agent 只能等待样本。", {"sample_count": sample_count}))

    counts = feature_snapshot.get("factor_counts") or {}
    news_count = int(counts.get("news_articles") or 0)
    market_total = int(counts.get("market_breadth_total") or 0)
    quant_count = int(counts.get("quant_factors") or 0)
    if news_count > 0 and market_total > 0 and quant_count > 0:
        checks.append(_check(review_id, "factor_evidence_alignment", "passed", "新闻、市场广度和量化因子证据完整。", dict(counts)))
    elif quant_count > 0 and market_total > 0:
        checks.append(_check(review_id, "factor_evidence_alignment", "warning", "缺少新闻证据，允许观察但不允许直接晋级模型。", dict(counts)))
    else:
        checks.append(_check(review_id, "factor_evidence_alignment", "failed", "关键因子证据不足，阻断模型迭代。", dict(counts)))

    failed = [item for item in checks if item["status"] == "failed"]
    warnings = [item for item in checks if item["status"] == "warning"]
    if failed:
        verification_status = "failed"
        gate_status = "blocked"
        next_state = "blocked"
    elif warnings:
        verification_status = "warning"
        gate_status = "observation_only"
        next_state = "candidate_monitor"
    else:
        verification_status = "passed"
        gate_status = "candidate_allowed"
        next_state = "candidate"

    if agent_review.get("status") == "waiting_for_samples":
        gate_status = "waiting_for_samples"
        next_state = "waiting_for_samples"

    return {
        "verification_status": verification_status,
        "checks": checks,
        "gate_result": {
            "status": gate_status,
            "next_state": next_state,
            "failed_checks": [item["check_type"] for item in failed],
            "warning_checks": [item["check_type"] for item in warnings],
            "blocked_actions": agent_review.get("blocked_actions") or [],
            "message": "自动核实通过，可进入候选观察。" if verification_status == "passed" else "自动核实未完全通过，仅允许受控观察或阻断。",
        },
    }