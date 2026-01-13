"""Model inference utilities for online prediction.

Functions:
- load_active_model(task): fetch active model registry row & load artifact + metadata
- build_feature_vector(session, symbol, trade_date): assemble feature vector in training order
- predict_symbol(session, symbol, horizons): returns dict with classification prob and regression returns

Assumptions:
- Model artifacts saved by train_signal_models.py (joblib with {'model','scaler'}).
- Metadata JSON contains 'categorical_mappings' and 'feature_base'.
- Active models exist for tasks: next_day_direction, fwd_ret_{H}d
"""
from __future__ import annotations
import json, os, datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from sqlalchemy.orm import Session
import sqlalchemy as sa

from ..core.models import StockDailyFeature, ModelRegistry

import joblib  # type: ignore

MODEL_DIR = Path('models')

CLASS_TASK = 'next_day_direction'
RET_TASKS = {
    '1d': 'fwd_ret_1d',
    '5d': 'fwd_ret_5d',
    '10d': 'fwd_ret_10d',
    '20d': 'fwd_ret_20d'
}

CATEGORICAL = ['agent_parse_mode','agent_sentiment_label']

class LoadedModel:
    def __init__(self, task: str, artifact_path: str, feature_names: List[str], meta: Dict):
        obj = joblib.load(artifact_path)
        self.model = obj['model']
        self.scaler = obj['scaler']
        self.task = task
        self.feature_names = feature_names
        self.meta = meta


def _load_meta_for_artifact(artifact_path: str) -> Dict:
    p = Path(artifact_path)
    meta_path = p.with_name(p.name.replace('.pkl', '_meta.json'))
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding='utf-8'))
    # fallback: search MODEL_DIR for *_meta.json prefix
    return {}


def load_active_model(session: Session, task: str) -> Optional[LoadedModel]:
    row = session.query(ModelRegistry).filter(ModelRegistry.task==task, ModelRegistry.is_active==True).order_by(ModelRegistry.version.desc()).first()
    if not row or not row.artifact_path:
        return None
    feature_names = []
    if row.features_used:
        try:
            feature_names = json.loads(row.features_used)
        except Exception:
            pass
    meta = _load_meta_for_artifact(row.artifact_path)
    return LoadedModel(task, row.artifact_path, feature_names, meta)


def _fetch_latest_feature_row(session: Session, symbol: str, trade_date: Optional[datetime.date]=None):
    q = session.query(StockDailyFeature).filter(StockDailyFeature.symbol==symbol)
    if trade_date:
        q = q.filter(StockDailyFeature.trade_date==trade_date)
    else:
        q = q.order_by(StockDailyFeature.trade_date.desc())
    return q.first()


def _value_or_nan(val):
    return float(val) if val is not None else np.nan


def build_feature_vector(row: StockDailyFeature, feature_names: List[str]):
    # feature_names includes base + one-hot columns (like agent_parse_mode__x)
    # We'll reconstruct categorical one-hot using meta mappings
    base_values = {}
    for name in feature_names:
        base_values[name] = 0.0  # init
    # Fill continuous features directly
    for name in feature_names:
        if name in ('agent_parse_mode','agent_sentiment_label'):  # raw categorical not present in final matrix
            continue
    # Direct mapping for known numeric columns
    for name in feature_names:
        if '__' not in name and hasattr(row, name):
            val = getattr(row, name)
            if val is not None:
                base_values[name] = float(val)
    # Categorical one-hot
    for name in feature_names:
        if '__' in name:
            prefix, cat_val = name.split('__',1)
            row_val = getattr(row, prefix, None)
            if row_val == cat_val:
                base_values[name] = 1.0
    vec = [base_values[n] for n in feature_names]
    # impute simple: replace NaN with column mean? Here just zero (scaler will adjust)
    return np.array(vec, dtype=float)


def predict_symbol(session: Session, symbol: str, horizons: List[str], trade_date: Optional[datetime.date]=None):
    row = _fetch_latest_feature_row(session, symbol, trade_date)
    if not row:
        return {'error': 'no feature row found'}
    results = {}
    # classification
    cls_model = load_active_model(session, CLASS_TASK)
    if cls_model:
        X_vec = build_feature_vector(row, cls_model.feature_names)
        X_scaled = cls_model.scaler.transform([X_vec])
        prob = cls_model.model.predict_proba(X_scaled)[0,1]
        results['direction_prob_up_1d'] = float(prob)
    # regression horizons
    for hz in horizons:
        task = RET_TASKS.get(hz)
        if not task:
            continue
        reg_model = load_active_model(session, task)
        if not reg_model:
            continue
        X_vec = build_feature_vector(row, reg_model.feature_names)
        X_scaled = reg_model.scaler.transform([X_vec])
        pred = reg_model.model.predict(X_scaled)[0]
        results[f'expected_return_{hz}'] = float(pred)
    results['symbol'] = symbol
    results['trade_date'] = row.trade_date.isoformat() if row.trade_date else None
    return results
