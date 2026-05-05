"""Agent 受控迭代建议兼容层。

当前版本只根据失败归因生成受控迭代建议，不写库、不调用 LLM、不自动修改模型或阈值。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional


DISCLAIMER = "Agent 复盘建议仅进入自动核实与门禁流程，不构成投资建议，也不会自动上线模型、调整阈值或执行交易。"


def _review_id(symbol: str, failure_analysis: dict) -> str:
    raw = json.dumps(
        {
            "symbol": symbol,
            "severity": failure_analysis.get("severity"),
            "root_causes": [cause.get("code") for cause in failure_analysis.get("root_causes") or []],
            "sample_count": failure_analysis.get("sample_count"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14]
    return f"ar_{symbol.replace('.', '_')}_{digest}"


def _proposal(action_type: str, label: str, rationale: str, guardrail: str, priority: str = "medium") -> dict:
    return {
        "type": action_type,
        "label": label,
        "priority": priority,
        "rationale": rationale,
        "guardrail": guardrail,
        "requires_approval": False,
        "requires_gate_pass": True,
    }


def build_agent_review(
    symbol: str,
    *,
    failure_analysis: Optional[dict] = None,
    feature_snapshot: Optional[dict] = None,
) -> dict:
    failure_analysis = failure_analysis or {}
    root_causes = failure_analysis.get("root_causes") or []
    severity = failure_analysis.get("severity") or "unknown"
    quality = failure_analysis.get("quality_snapshot") or {}
    proposed_actions = []

    cause_codes = {cause.get("code") for cause in root_causes}
    if "direction_miss" in cause_codes:
        proposed_actions.append(_proposal(
            "feature_review",
            "复核方向因子权重",
            "方向判断多次未命中，说明方向概率可能过度依赖单一模型输出。",
            "只生成受控配置候选；需通过数据核实、回测和影子观察门禁后才允许调整权重。",
            priority="high" if severity == "high" else "medium",
        ))
    if "large_price_error" in cause_codes or "interval_miss" in cause_codes:
        proposed_actions.append(_proposal(
            "risk_band_review",
            "复核波动率与区间宽度",
            "价格偏差或区间未命中提示近期波动可能被低估。",
            "不得直接扩大目标价或止损阈值；必须先验证历史区间命中率。",
            priority="high" if "large_price_error" in cause_codes else "medium",
        ))
    if "systematic_bias" in cause_codes:
        proposed_actions.append(_proposal(
            "bias_monitor",
            "加入系统性偏差观察",
            "模型近期存在同向高估或低估倾向。",
            "连续多个交易窗口确认后再进入再训练候选池。",
        ))

    coverage_notes = failure_analysis.get("coverage_notes") or []
    if coverage_notes:
        proposed_actions.append(_proposal(
            "data_coverage_review",
            "补齐复盘证据覆盖",
            coverage_notes[0],
            "补齐新闻、市场广度或量化因子快照后，再决定是否调整模型。",
        ))
    if not proposed_actions and severity != "unknown":
        proposed_actions.append(_proposal(
            "sample_monitor",
            "继续观察样本稳定性",
            "当前偏差尚未触发明确高风险动作。",
            "至少累积到下一个评估窗口后再生成调整建议。",
            priority="low",
        ))

    if severity == "unknown":
        headline = "暂无足够失败样本，Agent 暂不生成模型调整建议。"
        priority = "none"
        status = "waiting_for_samples"
    else:
        priority = "high" if severity == "high" else "medium" if severity == "medium" else "low"
        status = "pending_gate"
        headline = f"Agent 已生成 {len(proposed_actions)} 条受控迭代建议，等待自动门禁判断。"

    evidence = []
    if failure_analysis.get("headline"):
        evidence.append(failure_analysis["headline"])
    if quality.get("quality_grade"):
        score = quality.get("quality_score")
        evidence.append(f"预测质量：{quality.get('quality_grade')}，评分 {score if score is not None else '-'}。")
    if feature_snapshot:
        completeness = feature_snapshot.get("completeness_score")
        evidence.append(f"特征快照覆盖率：{completeness if completeness is not None else '-'}%。")

    return {
        "review_id": _review_id(symbol, failure_analysis),
        "symbol": symbol,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "priority": priority,
        "headline": headline,
        "evidence": evidence[:5],
        "proposed_actions": proposed_actions[:5],
        "blocked_actions": [
            "不会自动上线或替换模型",
            "不会自动调整交易阈值或仓位",
            "不会自动执行买入、卖出或调仓",
        ],
        "requires_human_review": False,
        "requires_gate_pass": bool(proposed_actions),
        "source": "failure_analysis_rule_agent",
        "disclaimer": DISCLAIMER,
    }