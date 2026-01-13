"""
Reports module - 报告与宏观模块

包含报告生成、宏观观测、宏观模型训练等功能。
"""

from .report import plain_summary, llm_summarize, generate_report_data
from .macro_pipeline import MacroTopic, MacroObservation, run_pipeline
from .macro_report import generate_and_store_macro_report
from .macro_reporter import MacroDailyReport
from .macro_model_trainer import run_training_job

__all__ = [
    'plain_summary',
    'llm_summarize',
    'generate_report_data',
    'MacroTopic',
    'MacroObservation',
    'run_pipeline',
    'generate_and_store_macro_report',
    'MacroDailyReport',
    'run_training_job',
]
