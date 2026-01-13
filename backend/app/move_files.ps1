# PowerShell脚本：将Python文件按功能分类移动到对应子文件夹

$appDir = "d:\workspace\mpj\aistock-full-project\backend\app"

# 定义文件到文件夹的映射
$fileMapping = @{
    # Core module - 核心基础设施
    "db.py" = "core"
    "models.py" = "core"
    "logging_config.py" = "core"
    
    # Data module - 数据获取
    "data_source.py" = "data"
    
    # Analysis module - 技术分析
    "signals.py" = "analysis"
    "stock_manager.py" = "analysis"
    
    # Prediction module - 预测与模型
    "forecast.py" = "prediction"
    "forecast_enhanced.py" = "prediction"
    "model_inference.py" = "prediction"
    
    # News module - 新闻处理
    "news_service.py" = "news"
    "news_crawler.py" = "news"
    "news_deduplication.py" = "news"
    "news_strategy.py" = "news"
    "llm_processor.py" = "news"
    "enhanced_news_scheduler.py" = "news"
    
    # Tasks module - 任务与调度
    "scheduler.py" = "tasks"
    "task_manager.py" = "tasks"
    "task_scheduler.py" = "tasks"
    
    # Reports module - 报告与宏观
    "report.py" = "reports"
    "macro_pipeline.py" = "reports"
    "macro_report.py" = "reports"
    "macro_reporter.py" = "reports"
    "macro_model_trainer.py" = "reports"
    
    # Utils module - 工具与辅助
    "mongo_storage.py" = "utils"
    "stock_profile_enrichment.py" = "utils"
    "stock_profile_validator.py" = "utils"
    "profile_updater.py" = "utils"
    "background_task_queue.py" = "utils"
    "agent_persistence.py" = "utils"
    "metrics.py" = "utils"
}

# 执行移动操作
foreach ($file in $fileMapping.Keys) {
    $sourcePath = Join-Path $appDir $file
    $targetDir = Join-Path $appDir $fileMapping[$file]
    $targetPath = Join-Path $targetDir $file
    
    if (Test-Path $sourcePath) {
        Write-Host "移动: $file -> $($fileMapping[$file])/"
        Move-Item -Path $sourcePath -Destination $targetPath -Force
    } else {
        Write-Host "未找到: $file"
    }
}

Write-Host "完成！所有文件已按功能分类"
