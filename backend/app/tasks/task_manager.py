"""
任务管理模块（task_manager）
模块概述
-------
本模块提供 TaskManager 类，用于统一管理异步任务的创建、调度与执行。
任务主要与股票相关的数据处理与报告生成相关（如生成报告、收集新闻等），
并通过数据库（SQLAlchemy 会话）持久化任务状态与结果。模块设计兼顾可扩展性、
并发控制与数据库一致性。
设计要点
-------
- 以 Task 表为中心，维护任务的创建、状态迁移（PENDING -> RUNNING -> COMPLETED/FAILED）与元信息。
- 使用轻量级并发控制（running_tasks 集合与 max_concurrent_tasks 限制）防止过度并发与重复执行。
- 所有 DB 操作通过 SessionLocal 上下文管理器进行，尽量在短事务内提交以减少锁等待。
- 将具体任务执行逻辑封装到独立方法（如 execute_report_task、execute_news_task、_generate_report、_collect_news_for_task）
    便于扩展与单元测试。
- 生成报告时保证“最新”标记（is_latest）的一致性：先将已有报告置为非最新并提交，再插入新报告并提交。
主要类与方法
-------
TaskManager
        属性：
                running_tasks: set - 正在执行的任务 ID 集合（用于防重入与并发限制）。
                max_concurrent_tasks: int - 最大并发任务数（默认 3）。
                _stopped: bool - 软停止标志，设为 True 后不再分发新任务。
        方法（摘要）：
                stop() / is_stopped()
                        控制任务管理器是否暂停分发新任务（软停止）。
                create_task(task_type, symbol, priority=5, metadata=None) -> Optional[int]
                        通用任务创建接口。会检查相同（symbol, task_type）是否已有 PENDING/RUNNING 任务以避免重复入队。
                        返回新任务 ID 或已存在任务 ID；异常时返回 None。
                create_report_task(symbol, priority=5) -> Optional[int]
                        为指定股票创建报告生成任务，内置避免重复排队的检查。
                check_and_create_missing_report_tasks() -> List[int]
                        扫描启用的自选股（Watchlist），为没有最新报告且未排队的股票创建报告任务（优先级较高）。
                execute_report_task(task_id) -> bool
                        报告生成任务执行器。负责任务状态迁移、调用 _generate_report 生成报告并更新任务状态与错误信息。
                _generate_report(symbol, session) -> bool
                        报告生成的核心逻辑（与数据库交互）。职责包括：
                            - 从 PriceDaily/Signal/Forecast 拉取最新数据；
                            - 计算 data_quality_score、prediction_confidence、analysis_summary；
                            - 将原有 is_latest=True 的报告标记为 False 并提交；
                            - 按 version 自增插入新报告并提交。
                        返回是否成功写入新报告。
                _calculate_data_quality(price_data, signal_data, forecasts) -> float
                        针对价格、技术信号与预测数据的启发式数据质量评分（0-10）。
                _calculate_prediction_confidence(forecasts) -> float
                        基于预测区间宽度计算置信度（0-1）。
                _generate_analysis_summary(symbol, price_data, signal_data, forecasts) -> str
                        生成面向普通投资者的简短文本摘要（注意避免提供法律/投资建议）。
                get_pending_tasks(limit=10) -> List[Dict]
                        列取当前 PENDING 任务，按优先级与创建时间排序，返回用于展示的字典列表。
                process_tasks()
                        用于将 PENDING 任务分派到异步执行（asyncio.create_task）。会检查并发上限并将任务 ID 放入 running_tasks。
                _execute_task_wrapper(task_id)
                        统一的任务执行包装器，根据 task_type 分派到相应执行器；确保 finally 中移除 running_tasks，避免泄漏。
                execute_news_task(task_id) -> bool
                        新闻收集任务执行器，状态迁移及异常处理模式与 execute_report_task 类似。
                _collect_news_for_task(task, session) -> bool
                        实际的新闻收集实现点（可调用策略调度器或手动收集），应捕获异常并返回成功/失败布尔值。
并发与运行时控制
-------
- 并发以 asyncio 为基础，process_tasks 将基于 max_concurrent_tasks 创建后台协程。
- running_tasks 用于记录已经被调度执行但尚未结束的任务 ID，避免重复调度相同任务。
- 提供 stop/is_stopped 用于软停止场景：外部可在停止标志设定后停止调用 process_tasks，从而实现优雅停机。
数据库事务与一致性
-------
- 每次对数据库的修改都在短事务内完成（通过 SessionLocal 上下文）。
- 生成报告时先把历史最新报告设置为非最新并提交，随后插入新报告并提交，降低并发插入导致的不一致性风险。
- 所有读取和写入均使用 SQLAlchemy Core/ORM 的 select/update/commit 模式，调用方需要保证 SessionLocal 正确配置。
错误处理策略
-------
- 任务执行器在捕获到异常时会：
        - 将任务状态设置为 FAILED；
        - 将异常消息写入 task.error_message；
        - 设置 completed_at 并提交事务。
- _generate_report 与 _collect_news_for_task 等下层方法应尽量返回布尔结果，异常由上层统一捕获并记录。
扩展点与注意事项
-------
- 新增任务类型：在 TaskType 中注册新类型，并在 _execute_task_wrapper 中加入分派分支，以及实现对应 execute_* 方法。
- 重试策略：当前实现没有内建重试；如需重试可在 execute_* 中加入重试计数与指数回退逻辑，或在数据库层记录重试次数。
- 测试：各 execute_* 方法与 _generate_report 等函数应尽量以可注入 session 的方式进行单元测试（使用事务回滚或独立测试 DB）。
- 并发安全：running_tasks 仅在单进程 asyncio 环境下有效；若部署为多进程或分布式，需要引入分布式锁（例如 Redis 锁）以避免重复执行。
- 性能与批量操作：当自选股数量较大时，check_and_create_missing_report_tasks 的扫描可考虑分页或批量查询优化。
示例用法（伪代码）
-------
        # 创建任务
        task_manager.create_task(TaskType.GENERATE_REPORT, "AAPL", priority=3)
        # 在 asyncio 循环中周期性调度
        async def scheduler_loop():
                while not task_manager.is_stopped():
                        await task_manager.process_tasks()
                        await asyncio.sleep(5)
        # 软停止
        task_manager.stop()
作者/维护
-------
该模块负责任务生命周期管理与任务执行的协调，建议与项目的模型定义（Task, Report, PriceDaily, Signal, Forecast, Watchlist, TaskStatus, TaskType）
以及 SessionLocal 配置保持一致。

"""
import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy import select, and_, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..core.db import SessionLocal
from ..core.models import Task, Report, Watchlist, PriceDaily, Signal, Forecast, TaskStatus, TaskType

logger = logging.getLogger(__name__)

class TaskManager:
    def __init__(self):
        # 正在运行中的任务ID集合：用于防重入与并发上限控制
        self.running_tasks = set()
        # 并发上限（见模块顶部“魔术数值说明”）：默认3
        self.max_concurrent_tasks = 3
        # 软停止标志：用于优雅停机或暂停分发新任务
        self._stopped = False
        
    def stop(self):
        """停止任务管理器"""
        self._stopped = True
        
    def is_stopped(self) -> bool:
        """检查任务管理器是否已停止"""
        return self._stopped
        
    def create_task(self, task_type: str, symbol: str, priority: int = 5, metadata: Optional[Dict[str, Any]] = None) -> Optional[int]:
        """创建新任务
        
        Args:
            task_type: 任务类型 (TaskType)
            symbol: 股票代码
            priority: 优先级 (1-10, 1最高)
            metadata: 任务元数据
            
        Returns:
            task_id: 创建的任务ID，如果失败返回None
        """
        try:
            with SessionLocal() as session:
                # 去重：检查是否已有相同任务在队列中（PENDING/RUNNING）
                existing_task = session.execute(
                    select(Task).where(
                        and_(
                            Task.symbol == symbol,
                            Task.task_type == task_type,
                            Task.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING])
                        )
                    )
                ).scalar_one_or_none()
                
                if existing_task:
                    logger.info(f"Task already exists for {symbol} with type {task_type}")
                    return existing_task.id
                
                # 创建新任务（默认 PENDING；priority 数值越小越优先）
                task = Task(
                    task_type=task_type,
                    symbol=symbol,
                    status=TaskStatus.PENDING,
                    priority=priority,
                    task_metadata=json.dumps(metadata) if metadata else None
                )
                
                session.add(task)
                session.commit()
                session.refresh(task)
                
                logger.info(f"Created task {task.id} for {symbol} with type {task_type}")
                return task.id
                
        except Exception as e:
            logger.error(f"Failed to create task for {symbol}: {e}")
            return None
        
    async def create_report_task(self, symbol: str, priority: int = 5) -> Optional[int]:
        """为指定股票创建报告生成任务"""
        with SessionLocal() as session:
            # 检查是否已有相同任务在队列中
            existing_task = session.execute(
                select(Task).where(
                    and_(
                        Task.symbol == symbol,
                        Task.task_type == TaskType.GENERATE_REPORT,
                        Task.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING])
                    )
                )
            ).scalar_one_or_none()
            
            if existing_task:
                logger.info(f"Task already exists for {symbol}, task_id: {existing_task.id}")
                return existing_task.id
            
            # 创建新任务（自动补齐通常赋予更高优先级，如 3）
            new_task = Task(
                task_type=TaskType.GENERATE_REPORT,
                symbol=symbol,
                priority=priority,
                task_metadata=json.dumps({"auto_created": True})
            )
            session.add(new_task)
            session.commit()
            session.refresh(new_task)
            
            logger.info(f"Created report task for {symbol}, task_id: {new_task.id}")
            return new_task.id
    
    async def check_and_create_missing_report_tasks(self) -> List[int]:
        """
        检查所有自选股票，为“没有最新报告且没有排队任务”的股票创建报告任务。

        策略：
        - 先查 is_latest=True 的报告是否存在；如不存在再查是否已有 PENDING/RUNNING 的报告任务；
        - 若均无，则创建优先级较高（3）的补齐任务。
        """
        created_tasks = []
        
        with SessionLocal() as session:
            # 获取所有启用的自选股票
            watchlist_stocks = session.execute(
                select(Watchlist.symbol).where(Watchlist.enabled == True)
            ).scalars().all()
            
            for symbol in watchlist_stocks:
                # 检查是否有最新报告（is_latest=True）
                has_report = session.execute(
                    select(Report).where(
                        and_(Report.symbol == symbol, Report.is_latest == True)
                    )
                ).scalar_one_or_none()
                
                if not has_report:
                    # 若无最新报告，再检查是否有待处理任务（避免重复排队）
                    has_pending_task = session.execute(
                        select(Task).where(
                            and_(
                                Task.symbol == symbol,
                                Task.task_type == TaskType.GENERATE_REPORT,
                                Task.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING])
                            )
                        )
                    ).scalar_one_or_none()
                    
                    if not has_pending_task:
                        task_id = await self.create_report_task(symbol, priority=3)
                        if task_id:
                            created_tasks.append(task_id)
        
        logger.info(f"Created {len(created_tasks)} missing report tasks")
        return created_tasks
    
    async def execute_report_task(self, task_id: int) -> bool:
        """执行报告生成任务"""
        with SessionLocal() as session:
            # 获取任务
            task = session.execute(
                select(Task).where(Task.id == task_id)
            ).scalar_one_or_none()
            
            if not task or task.status != TaskStatus.PENDING:
                logger.warning(f"Task {task_id} not found or not pending")
                return False
            
            # 状态迁移：PENDING → RUNNING，并记录开始时间
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.utcnow()
            session.commit()
            
            try:
                # 生成报告（核心逻辑在 _generate_report）
                success = await self._generate_report(task.symbol, session)
                
                if success:
                    task.status = TaskStatus.COMPLETED
                    task.completed_at = datetime.utcnow()
                    logger.info(f"Report task {task_id} completed for {task.symbol}")
                else:
                    task.status = TaskStatus.FAILED
                    task.error_message = "Failed to generate report"
                    task.completed_at = datetime.utcnow()
                    logger.error(f"Report task {task_id} failed for {task.symbol}")
                
                session.commit()
                return success
                
            except Exception as e:
                task.status = TaskStatus.FAILED
                task.error_message = str(e)
                task.completed_at = datetime.utcnow()
                session.commit()
                logger.error(f"Report task {task_id} failed with exception: {e}")
                return False
    
        async def _generate_report(self, symbol: str, session) -> bool:
                """生成股票报告

                合同（Contract）：
                - 输入：symbol 必填；session 为当前数据库会话。
                - 输出：bool，表示是否成功入库一条新的“最新”（is_latest=True）报告。
                - 副作用：
                    1) 将该 symbol 之前 is_latest=True 的报告全部置为 False（一次性更新并提交）。
                    2) 以 version 自增方式创建新报告（保持可追溯）。
                - 失败模式：任意步骤异常返回 False；异常由上层捕获并写入 task.error_message。
                """
        try:
            # 获取最新价格数据
            latest_price = session.execute(
                select(PriceDaily).where(PriceDaily.symbol == symbol)
                .order_by(PriceDaily.trade_date.desc())
                .limit(1)
            ).scalar_one_or_none()
            
            # 获取最新信号数据
            latest_signal = session.execute(
                select(Signal).where(Signal.symbol == symbol)
                .order_by(Signal.trade_date.desc())
                .limit(1)
            ).scalar_one_or_none()
            
            # 获取预测数据
            forecasts = session.execute(
                select(Forecast).where(Forecast.symbol == symbol)
                .order_by(Forecast.target_date)
            ).scalars().all()
            
            # 构建报告数据
            price_data = None
            if latest_price:
                price_data = {
                    "trade_date": latest_price.trade_date.isoformat(),
                    "close": float(latest_price.close) if latest_price.close is not None else None,
                    "open": float(latest_price.open) if latest_price.open is not None else None,
                    "high": float(latest_price.high) if latest_price.high is not None else None,
                    "low": float(latest_price.low) if latest_price.low is not None else None,
                    "pct_chg": float(latest_price.pct_chg) if latest_price.pct_chg is not None else None,
                    "vol": latest_price.vol
                }
            
            signal_data = None
            if latest_signal:
                signal_data = {
                    "trade_date": latest_signal.trade_date.isoformat(),
                    "ma_short": float(latest_signal.ma_short) if latest_signal.ma_short is not None else None,
                    "ma_long": float(latest_signal.ma_long) if latest_signal.ma_long is not None else None,
                    "rsi": float(latest_signal.rsi) if latest_signal.rsi is not None else None,
                    "macd": float(latest_signal.macd) if latest_signal.macd is not None else None,
                    "signal_score": float(latest_signal.signal_score) if latest_signal.signal_score is not None else None,
                    "action": latest_signal.action
                }
            
            forecast_data = []
            for f in forecasts:
                forecast_data.append({
                    "target_date": f.target_date.isoformat(),
                    "yhat": float(f.yhat) if f.yhat is not None else None,
                    "yhat_lower": float(f.yhat_lower) if f.yhat_lower is not None else None,
                    "yhat_upper": float(f.yhat_upper) if f.yhat_upper is not None else None,
                    "model": f.model
                })
            
            # 计算数据质量评分（0-10，见 _calculate_data_quality）
            data_quality_score = self._calculate_data_quality(latest_price, latest_signal, forecasts)
            
            # 计算预测置信度（0-1，见 _calculate_prediction_confidence）
            prediction_confidence = self._calculate_prediction_confidence(forecasts)
            
            # 生成分析摘要（面向用户的简短文本）
            analysis_summary = self._generate_analysis_summary(symbol, latest_price, latest_signal, forecasts)
            
            # 获取当前最大版本号
            max_version = session.execute(
                select(Report.version).where(Report.symbol == symbol)
                .order_by(Report.version.desc())
                .limit(1)
            ).scalar_one_or_none()
            
            next_version = (max_version or 0) + 1
            
            # 将之前的报告标记为非最新 - 使用事务确保一致性
            session.execute(
                update(Report)
                .where(and_(Report.symbol == symbol, Report.is_latest == True))
                .values(is_latest=False)
            )
            
            # 立即提交更新，确保数据一致性
            session.commit()
            
            # 创建新报告（注意：将部分对象转为 JSON 文本存储）
            new_report = Report(
                symbol=symbol,
                version=next_version,
                latest_price_data=json.dumps(price_data) if price_data else None,
                signal_data=json.dumps(signal_data) if signal_data else None,
                forecast_data=json.dumps(forecast_data) if forecast_data else None,
                analysis_summary=analysis_summary,
                data_quality_score=data_quality_score,
                prediction_confidence=prediction_confidence,
                is_latest=True
            )
            
            session.add(new_report)
            session.commit()
            
            logger.info(f"Generated report v{next_version} for {symbol}")
            return True
            
        except Exception as e:
            logger.error(f"Error generating report for {symbol}: {e}")
            return False
    
    def _calculate_data_quality(self, price_data, signal_data, forecasts) -> float:
        """计算数据质量评分 (0-10)

        经验规则：
        - 有最近价格且带有效成交量 → 加权加分。
        - 技术指标信号越完整（MA/RSI/MACD）→ 分数越高。
        - 预测数据条数越多 → 最高再加 2 分（设上限）。
        注：此为启发式打分，仅用于 UI 提示，不代表统计意义。
        """
        score = 0.0
        
        # 价格数据质量 (40%)
        if price_data and price_data.close:
            score += 4.0
            if price_data.vol and price_data.vol > 0:
                score += 1.0
        
        # 信号数据质量 (40%)
        if signal_data:
            signal_count = sum(1 for v in [signal_data.ma_short, signal_data.ma_long, 
                                         signal_data.rsi, signal_data.macd] if v is not None)
            score += (signal_count / 4) * 4.0
        
        # 预测数据质量 (20%)
        if forecasts:
            valid_forecasts = sum(1 for f in forecasts if f.yhat is not None)
            if valid_forecasts > 0:
                score += min(2.0, valid_forecasts / 5 * 2.0)
        
        return round(score, 2)
    
    def _calculate_prediction_confidence(self, forecasts) -> float:
        """计算预测置信度 (0-1)

        方法：使用预测区间宽度相对 yhat 的比率作为不确定性度量；
        区间越窄 → 置信度越高；限制在 [0,1]。
        """
        if not forecasts:
            return 0.0
        
        # 基于预测区间的宽度来评估置信度
        valid_intervals = []
        for f in forecasts:
            if f.yhat and f.yhat_lower and f.yhat_upper:
                yhat = float(f.yhat)
                yhat_lower = float(f.yhat_lower)
                yhat_upper = float(f.yhat_upper)
                interval_width = abs(yhat_upper - yhat_lower)
                relative_width = interval_width / max(abs(yhat), 1)  # 避免除零
                valid_intervals.append(relative_width)
        
        if not valid_intervals:
            return 0.0
        
        # 区间越窄，置信度越高
        avg_relative_width = sum(valid_intervals) / len(valid_intervals)
        confidence = max(0.0, min(1.0, 1.0 - avg_relative_width))
        
        return round(confidence, 3)
    
    def _generate_analysis_summary(self, symbol: str, price_data, signal_data, forecasts) -> str:
        """生成分析摘要

        目标：
        - 面向普通投资者的简洁描述，包含收盘价、涨跌幅、信号建议与最近预测。
        - 控制长度，避免夸大或产生投资建议责任。
        """
        summary_parts = []
        
        if price_data and price_data.close:
            pct_chg = float(price_data.pct_chg) if price_data.pct_chg is not None else 0
            trend = "上涨" if pct_chg > 0 else "下跌" if pct_chg < 0 else "平盘"
            summary_parts.append(f"最新收盘价 {float(price_data.close):.2f}，{trend} {abs(pct_chg):.2f}%")
        
        if signal_data:
            if signal_data.action:
                summary_parts.append(f"技术信号：{signal_data.action}")
            if signal_data.signal_score is not None:
                summary_parts.append(f"信号评分：{float(signal_data.signal_score):.1f}")
        
        if forecasts:
            future_forecasts = [f for f in forecasts if f.target_date > datetime.now().date()]
            if future_forecasts:
                next_forecast = future_forecasts[0]
                if next_forecast.yhat:
                    summary_parts.append(f"短期预测：{float(next_forecast.yhat):.2f}")
        
        return " | ".join(summary_parts) if summary_parts else f"{symbol} 数据分析报告已生成"
    
    async def get_pending_tasks(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取待处理任务"""
        with SessionLocal() as session:
            tasks = session.execute(
                select(Task).where(Task.status == TaskStatus.PENDING)
                .order_by(Task.priority.asc(), Task.created_at.asc())
                .limit(limit)
            ).scalars().all()
            
            return [
                {
                    "id": task.id,
                    "symbol": task.symbol,
                    "task_type": task.task_type,
                    "priority": task.priority,
                    "created_at": task.created_at.isoformat()
                }
                for task in tasks
            ]
    
    async def process_tasks(self):
        """处理待处理的任务"""
        # 并发控制：若已达上限则本轮不再分发
        if len(self.running_tasks) >= self.max_concurrent_tasks:
            return
        
        with SessionLocal() as session:
            # 获取待处理任务（按优先级升序、创建时间升序排队）
            tasks = session.execute(
                select(Task).where(Task.status == TaskStatus.PENDING)
                .order_by(Task.priority.asc(), Task.created_at.asc())
                .limit(self.max_concurrent_tasks - len(self.running_tasks))
            ).scalars().all()
            
            for task in tasks:
                if task.id not in self.running_tasks:
                    self.running_tasks.add(task.id)
                    # 异步执行任务：封装到 _execute_task_wrapper 中统一处理
                    asyncio.create_task(self._execute_task_wrapper(task.id))
    
    async def _execute_task_wrapper(self, task_id: int):
        """任务执行包装器

        作用：根据任务类型分派到对应处理器；确保 finally 中移除 running 状态，避免泄漏。
        """
        try:
            if task_id in self.running_tasks:
                # 获取任务类型并执行相应的处理器
                with SessionLocal() as session:
                    task = session.execute(
                        select(Task).where(Task.id == task_id)
                    ).scalar_one_or_none()
                    
                    if task:
                        if task.task_type == TaskType.GENERATE_REPORT.value:
                            await self.execute_report_task(task_id)
                        elif task.task_type == TaskType.FETCH_NEWS.value:
                            await self.execute_news_task(task_id)
                        else:
                            logger.warning(f"Unknown task type: {task.task_type}")
        finally:
            self.running_tasks.discard(task_id)
    
    async def execute_news_task(self, task_id: int) -> bool:
        """执行新闻收集任务"""
        with SessionLocal() as session:
            # 获取任务
            task = session.execute(
                select(Task).where(Task.id == task_id)
            ).scalar_one_or_none()
            
            if not task or task.status != TaskStatus.PENDING:
                logger.warning(f"News task {task_id} not found or not pending")
                return False
            
            # 状态迁移：PENDING → RUNNING，并记录开始时间
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.utcnow()
            session.commit()
            
            try:
                # 执行新闻收集（智能策略或手动指定 symbol）
                success = await self._collect_news_for_task(task, session)
                
                if success:
                    task.status = TaskStatus.COMPLETED
                    task.completed_at = datetime.utcnow()
                    logger.info(f"News task {task_id} completed for {task.symbol}")
                else:
                    task.status = TaskStatus.FAILED
                    task.error_message = "Failed to collect news"
                    task.completed_at = datetime.utcnow()
                    logger.error(f"News task {task_id} failed for {task.symbol}")
                
                session.commit()
                return success
                
            except Exception as e:
                task.status = TaskStatus.FAILED
                task.error_message = str(e)
                task.completed_at = datetime.utcnow()
                session.commit()
                logger.error(f"News task {task_id} failed with exception: {e}")
                return False
    
    async def _collect_news_for_task(self, task: Task, session) -> bool:
        """为任务收集新闻"""
        try:
            from ..news.news_strategy import NewsStrategyScheduler
            
            if task.symbol == "ALL":
                # 执行智能新闻收集
                strategy_scheduler = NewsStrategyScheduler()
                result = await strategy_scheduler.run_intelligent_collection()
                return result.get("status") == "completed"
            else:
                # 为特定股票收集新闻
                from ..tasks.scheduler import run_manual_news_collection
                await run_manual_news_collection(task.symbol)
                return True
                
        except Exception as e:
            logger.error(f"Error collecting news: {e}")
            return False

# 全局任务管理器实例
task_manager = TaskManager()
