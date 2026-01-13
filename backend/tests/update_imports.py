#!/usr/bin/env python3
"""
更新backend/tests中所有测试文件的import语句
"""

import os
from pathlib import Path

# 定义导入映射关系
IMPORT_MAPPING = {
    # Core imports
    'from app.core.db import': 'from app.core.db import',
    'from app.core.models import': 'from app.core.models import',
    'from app.core.logging_config import': 'from app.core.logging_config import',
    
    # Data imports
    'from app.data.data_source import': 'from app.data.data_source import',
    
    # Analysis imports
    'from app.analysis.signals import': 'from app.analysis.signals import',
    'from app.analysis.stock_manager import': 'from app.analysis.stock_manager import',
    
    # Prediction imports
    'from app.prediction.forecast import': 'from app.prediction.forecast import',
    'from app.prediction.forecast_enhanced import': 'from app.prediction.forecast_enhanced import',
    'from app.prediction.model_inference import': 'from app.prediction.model_inference import',
    
    # News imports
    'from app.news.news_service import': 'from app.news.news_service import',
    'from app.news.news_crawler import': 'from app.news.news_crawler import',
    'from app.news.news_deduplication import': 'from app.news.news_deduplication import',
    'from app.news.news_strategy import': 'from app.news.news_strategy import',
    'from app.news.llm_processor import': 'from app.news.llm_processor import',
    'from app.news.enhanced_news_scheduler import': 'from app.news.enhanced_news_scheduler import',
    
    # Tasks imports
    'from app.tasks.scheduler import': 'from app.tasks.scheduler import',
    'from app.tasks.task_manager import': 'from app.tasks.task_manager import',
    'from app.tasks.task_scheduler import': 'from app.tasks.task_scheduler import',
    
    # Reports imports
    'from app.reports.report import': 'from app.reports.report import',
    'from app.reports.macro_pipeline import': 'from app.reports.macro_pipeline import',
    'from app.reports.macro_report import': 'from app.reports.macro_report import',
    'from app.reports.macro_reporter import': 'from app.reports.macro_reporter import',
    'from app.reports.macro_model_trainer import': 'from app.reports.macro_model_trainer import',
    
    # Utils imports
    'from app.utils.mongo_storage import': 'from app.utils.mongo_storage import',
    'from app.utils.stock_profile_enrichment import': 'from app.utils.stock_profile_enrichment import',
    'from app.utils.stock_profile_validator import': 'from app.utils.stock_profile_validator import',
    'from app.utils.profile_updater import': 'from app.utils.profile_updater import',
    'from app.utils.background_task_queue import': 'from app.utils.background_task_queue import',
    'from app.utils.agent_persistence import': 'from app.utils.agent_persistence import',
    'from app.utils.metrics import': 'from app.utils.metrics import',
}

def update_file_imports(file_path: str) -> bool:
    """更新单个文件的import语句"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        
        # 替换所有的import语句
        for old_import, new_import in IMPORT_MAPPING.items():
            content = content.replace(old_import, new_import)
        
        # 如果内容发生了变化，写回文件
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
        return False
    except Exception as e:
        print(f"处理文件 {file_path} 时出错: {e}")
        return False

def main():
    """主函数"""
    tests_dir = Path("d:/workspace/mpj/aistock-full-project/backend/tests")
    
    # 所有Python文件
    py_files = list(tests_dir.rglob("*.py"))
    
    updated_count = 0
    skipped_count = 0
    
    for py_file in py_files:
        if '__pycache__' in str(py_file):
            continue
            
        if update_file_imports(str(py_file)):
            print(f"✓ 更新: {py_file.relative_to(tests_dir)}")
            updated_count += 1
        else:
            skipped_count += 1
    
    print(f"\n完成！共更新 {updated_count} 个文件，跳过 {skipped_count} 个文件")

if __name__ == '__main__':
    main()
