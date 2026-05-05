"""潜力股票发现服务。"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.models import OpportunityCandidate, StockPoolMember, StockProfile, UserPosition, Watchlist
from ..data.data_source import normalize_symbol
from ..quant_engine.models import QEPrediction, QESignal


AUTO_PIN_SCORE = 82.0
AUTO_PIN_CONFIDENCE = 0.68
AUTO_PIN_MAX_RISK = 45.0
PENDING_SCORE = 66.0
PENDING_CONFIDENCE = 0.50
PENDING_MAX_RISK = 62.0


def _to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _norm_confidence(value: Any) -> float:
    raw = _to_float(value, 0.0) or 0.0
    return raw / 100.0 if raw > 1 else raw


def _norm_return(value: Any) -> float:
    raw = _to_float(value, 0.0) or 0.0
    return raw * 100.0 if -1.0 <= raw <= 1.0 else raw


def _risk_level(risk_score: float) -> str:
    if risk_score >= 70:
        return "high"
    if risk_score >= 45:
        return "medium"
    return "low"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _latest_signals(session: Session, days: int, scan_limit: int) -> list[QESignal]:
    since = date.today() - timedelta(days=days)
    rows = session.execute(
        select(QESignal)
        .where(QESignal.signal_date >= since)
        .order_by(QESignal.signal_date.desc(), QESignal.rank.asc().nullslast(), QESignal.score.desc())
        .limit(max(scan_limit * 5, scan_limit))
    ).scalars().all()
    seen: set[str] = set()
    out: list[QESignal] = []
    for row in rows:
        if row.symbol in seen:
            continue
        seen.add(row.symbol)
        out.append(row)
        if len(out) >= scan_limit:
            break
    return out


def _latest_predictions(session: Session, symbols: list[str], days: int) -> dict[str, QEPrediction]:
    if not symbols:
        return {}
    since = date.today() - timedelta(days=days)
    rows = session.execute(
        select(QEPrediction)
        .where(QEPrediction.symbol.in_(symbols), QEPrediction.predict_date >= since)
        .order_by(QEPrediction.predict_date.desc(), QEPrediction.created_at.desc())
    ).scalars().all()
    out: dict[str, QEPrediction] = {}
    for row in rows:
        out.setdefault(row.symbol, row)
    return out


def _profile_map(session: Session, symbols: list[str]) -> dict[str, StockProfile]:
    if not symbols:
        return {}
    return {row.symbol: row for row in session.execute(select(StockProfile).where(StockProfile.symbol.in_(symbols))).scalars().all()}


def _active_pool_symbols(session: Session) -> set[str]:
    return {
        row[0]
        for row in session.execute(select(StockPoolMember.symbol).where(StockPoolMember.exit_date.is_(None))).all()
    }


def _pinned_symbols(session: Session) -> set[str]:
    return {row[0] for row in session.execute(select(Watchlist.symbol).where(Watchlist.pinned.is_(True))).all()}


def _holding_symbols(session: Session, portfolio_id: str = "default") -> set[str]:
    return {
        row[0]
        for row in session.execute(
            select(UserPosition.symbol).where(UserPosition.portfolio_id == portfolio_id, UserPosition.quantity > 0)
        ).all()
    }


def _score_signal(signal: QESignal, prediction: Optional[QEPrediction]) -> tuple[float, float, float, list[str]]:
    signal_score = _to_float(signal.score, 50.0) or 50.0
    risk_score = _to_float(signal.risk_score, 50.0) or 50.0
    signal_conf = _norm_confidence(signal.confidence)
    pred_conf = _norm_confidence(prediction.confidence) if prediction else 0.0
    confidence = max(signal_conf, pred_conf)
    pred_ret = _norm_return(signal.predicted_return)
    if prediction and prediction.predicted_return is not None:
        pred_ret = max(pred_ret, _norm_return(prediction.predicted_return))
    prob_up = _norm_confidence(signal.direction_prob_up)
    if prediction and prediction.direction_prob_up is not None:
        prob_up = max(prob_up, _norm_confidence(prediction.direction_prob_up))

    action_bonus = {"strong_buy": 10.0, "buy": 6.0, "hold": 0.0, "sell": -18.0, "strong_sell": -30.0}.get(signal.action, 0.0)
    score = signal_score * 0.48 + confidence * 100 * 0.22 + max(pred_ret, 0.0) * 1.2 + prob_up * 100 * 0.16 - risk_score * 0.18 + action_bonus
    score = max(0.0, min(100.0, score))
    reasons = [
        f"量化信号 {signal.action}，综合分 {signal_score:.1f}",
        f"模型置信度 {confidence * 100:.1f}%",
        f"预期收益 {pred_ret:.2f}%",
        f"风险分 {risk_score:.1f}",
    ]
    return score, confidence, risk_score, reasons


def _recommended_action(score: float, confidence: float, risk_score: float, action: str) -> str:
    if score >= AUTO_PIN_SCORE and confidence >= AUTO_PIN_CONFIDENCE and risk_score <= AUTO_PIN_MAX_RISK and action in {"strong_buy", "buy"}:
        return "auto_pin"
    if score >= PENDING_SCORE and confidence >= PENDING_CONFIDENCE and risk_score <= PENDING_MAX_RISK:
        return "review"
    return "watch"


def _upsert_stock_pool(session: Session, symbol: str, name: Optional[str], notes: str) -> None:
    today = date.today()
    member = session.execute(select(StockPoolMember).where(StockPoolMember.symbol == symbol).limit(1)).scalar_one_or_none()
    if member:
        member.last_seen_date = today
        member.exit_date = None
        member.source = "opportunity_agent"
        member.notes = notes
    else:
        session.add(StockPoolMember(
            symbol=symbol,
            first_seen_date=today,
            last_seen_date=today,
            source="opportunity_agent",
            notes=notes,
        ))
    profile = session.execute(select(StockProfile).where(StockProfile.symbol == symbol).limit(1)).scalar_one_or_none()
    if profile is None:
        session.add(StockProfile(symbol=symbol, company_name=name, market="A股"))
    elif name and not profile.company_name:
        profile.company_name = name


def _pin_watchlist(session: Session, symbol: str, name: Optional[str], score: float) -> None:
    watch = session.execute(select(Watchlist).where(Watchlist.symbol == symbol).limit(1)).scalar_one_or_none()
    if watch is None:
        watch = Watchlist(symbol=symbol)
        session.add(watch)
    watch.name = name or watch.name
    watch.status = "active"
    watch.enabled = True
    watch.source = "opportunity_agent"
    watch.score = score
    watch.investment_potential = score
    watch.pinned = True
    watch.last_active_at = _utcnow()


def _candidate_row(candidate: OpportunityCandidate) -> dict[str, Any]:
    return {
        "id": candidate.id,
        "symbol": candidate.symbol,
        "name": candidate.name,
        "source": candidate.source,
        "status": candidate.status,
        "opportunityScore": candidate.opportunity_score,
        "confidence": candidate.confidence,
        "riskLevel": candidate.risk_level,
        "recommendedAction": candidate.recommended_action,
        "rationale": candidate.rationale,
        "evidence": candidate.evidence_json or {},
        "autoPinned": candidate.auto_pinned,
        "discoveredAt": candidate.discovered_at.isoformat() if candidate.discovered_at else None,
        "expiresAt": candidate.expires_at.isoformat() if candidate.expires_at else None,
        "reviewedAt": candidate.reviewed_at.isoformat() if candidate.reviewed_at else None,
        "reviewNotes": candidate.review_notes,
    }


def discover_opportunities(
    session: Session,
    *,
    scan_limit: int = 120,
    max_candidates: int = 20,
    auto_pin: bool = True,
    portfolio_id: str = "default",
) -> dict[str, Any]:
    signals = _latest_signals(session, days=10, scan_limit=scan_limit)
    symbols = [row.symbol for row in signals]
    predictions = _latest_predictions(session, symbols, days=10)
    profiles = _profile_map(session, symbols)
    pinned = _pinned_symbols(session)
    held = _holding_symbols(session, portfolio_id)
    active_pool = _active_pool_symbols(session)

    scored: list[tuple[float, OpportunityCandidate]] = []
    skipped: dict[str, int] = {"pinned": 0, "held": 0, "lowScore": 0}
    for signal in signals:
        symbol = normalize_symbol(signal.symbol)
        if symbol in pinned:
            skipped["pinned"] += 1
            continue
        if symbol in held:
            skipped["held"] += 1
            continue
        prediction = predictions.get(symbol)
        score, confidence, risk_score, reasons = _score_signal(signal, prediction)
        action = _recommended_action(score, confidence, risk_score, signal.action)
        if action == "watch":
            skipped["lowScore"] += 1
            continue
        profile = profiles.get(symbol)
        name = profile.company_name if profile else None
        evidence = {
            "signalDate": signal.signal_date.isoformat() if signal.signal_date else None,
            "signalAction": signal.action,
            "signalScore": _to_float(signal.score),
            "riskScore": risk_score,
            "rank": signal.rank,
            "directionProbUp": signal.direction_prob_up,
            "predictedReturn": signal.predicted_return,
            "predictionDate": prediction.predict_date.isoformat() if prediction and prediction.predict_date else None,
            "predictionConfidence": prediction.confidence if prediction else None,
            "alreadyInPool": symbol in active_pool,
            "factors": signal.factors_json or {},
        }
        candidate = session.execute(
            select(OpportunityCandidate)
            .where(OpportunityCandidate.symbol == symbol, OpportunityCandidate.source == "opportunity_agent")
            .order_by(OpportunityCandidate.discovered_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if candidate is None:
            candidate = OpportunityCandidate(symbol=symbol, source="opportunity_agent")
            session.add(candidate)
        candidate.name = name
        candidate.status = "auto_pinned" if action == "auto_pin" and auto_pin else "pending"
        candidate.opportunity_score = round(score, 2)
        candidate.confidence = round(confidence, 4)
        candidate.risk_level = _risk_level(risk_score)
        candidate.recommended_action = action
        candidate.rationale = "；".join(reasons)
        candidate.evidence_json = evidence
        candidate.auto_pinned = action == "auto_pin" and auto_pin
        now = _utcnow()
        candidate.discovered_at = now
        candidate.expires_at = now + timedelta(days=7)

        if candidate.auto_pinned:
            _upsert_stock_pool(session, symbol, name, f"机会发现自动入池，score={score:.1f}")
            _pin_watchlist(session, symbol, name, score)
        scored.append((score, candidate))

    scored.sort(key=lambda item: item[0], reverse=True)
    selected = [candidate for _, candidate in scored[:max_candidates]]
    session.flush()
    return {
        "ok": True,
        "scanned": len(signals),
        "skipped": skipped,
        "autoPinnedCount": sum(1 for item in selected if item.auto_pinned),
        "pendingCount": sum(1 for item in selected if item.status == "pending"),
        "candidates": [_candidate_row(item) for item in selected],
    }


def list_opportunity_candidates(
    session: Session,
    *,
    status: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    stmt = select(OpportunityCandidate)
    if status:
        stmt = stmt.where(OpportunityCandidate.status == status)
    rows = session.execute(
        stmt.order_by(OpportunityCandidate.discovered_at.desc(), OpportunityCandidate.opportunity_score.desc()).limit(limit)
    ).scalars().all()
    return [_candidate_row(row) for row in rows]


def approve_candidate(session: Session, symbol: str, *, notes: Optional[str] = None) -> dict[str, Any]:
    symbol = normalize_symbol(symbol)
    candidate = session.execute(
        select(OpportunityCandidate)
        .where(OpportunityCandidate.symbol == symbol)
        .order_by(OpportunityCandidate.discovered_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if candidate is None:
        raise ValueError("candidate not found")
    _upsert_stock_pool(session, symbol, candidate.name, notes or "用户确认机会发现候选入池")
    _pin_watchlist(session, symbol, candidate.name, candidate.opportunity_score or 0.0)
    candidate.status = "approved"
    candidate.reviewed_at = _utcnow()
    candidate.review_notes = notes
    candidate.auto_pinned = True
    session.flush()
    return _candidate_row(candidate)