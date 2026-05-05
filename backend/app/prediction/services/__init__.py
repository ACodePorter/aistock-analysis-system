"""
预测服务层

prediction_service    — 预测记录与评估
monitoring_service    — 预测监控与失败检测
training_service      — 再训练与因子 A/B 测试
continuous_learning   — 闭环调度器
signal_engine         — 交易信号生成引擎（预测 → Buy/Sell/Hold）
portfolio_optimizer   — 投资组合优化（信号 → 仓位分配 + 风控）
paper_trading         — 模拟实盘交易系统（真实时间流验证）
"""
