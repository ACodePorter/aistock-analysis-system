"""Per-symbol 数据管道执行记录工具。

提供 `record_pipeline_run` 上下文管理器，可在调度器 / API 调用的关键步骤里包裹执行块，
自动把 status / duration / error_message / log_excerpt 写入 `pipeline_runs`。

设计要点：
- 不依赖调用方事先准备 Session：内部开一个短事务写入失败时静默 rollback，
  不会把诊断失败升级成业务错误。
- 捕获本次执行期间该 logger 产生的日志尾部（约 2KB），便于前端 Drawer 展示。
- `mark_skipped(message)` / `mark_success(message)` 让调用侧显式标记分支。
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator, Optional

from ..core.db import SessionLocal
from ..core.models import PipelineRun


_MAX_LOG_CHARS = 2048
_DEFAULT_TARGET_LOGGERS = (
    "app.tasks.scheduler",
    "app.prediction.forecast",
    "app.data.data_source",
)


class _TailHandler(logging.Handler):
    """环形缓存最近 N 条日志的 handler；输出时拼接为尾部字符串。"""

    def __init__(self, level: int = logging.INFO, max_chars: int = _MAX_LOG_CHARS) -> None:
        super().__init__(level=level)
        self._buffer: list[str] = []
        self._max_chars = max_chars
        self.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            return
        self._buffer.append(msg)
        # 维护尾部长度在限制以内
        total = sum(len(x) + 1 for x in self._buffer)
        while self._buffer and total > self._max_chars:
            dropped = self._buffer.pop(0)
            total -= len(dropped) + 1

    def as_excerpt(self) -> Optional[str]:
        if not self._buffer:
            return None
        return "\n".join(self._buffer)[-self._max_chars:]


class PipelineRunContext:
    """上下文对象，供调用侧在 try 块内标记成功 / 跳过 / 追加消息。"""

    def __init__(self) -> None:
        self.status: str = "success"
        self.message: Optional[str] = None
        self.error_message: Optional[str] = None
        self.extra_log: Optional[str] = None

    def mark_success(self, message: Optional[str] = None) -> None:
        self.status = "success"
        if message is not None:
            self.message = message

    def mark_skipped(self, message: Optional[str] = None) -> None:
        self.status = "skipped"
        if message is not None:
            self.message = message

    def mark_failed(self, error_message: str) -> None:
        self.status = "failed"
        self.error_message = error_message


@contextmanager
def record_pipeline_run(
    symbol: str,
    run_type: str,
    trigger: str = "scheduler",
    *,
    target_loggers: tuple[str, ...] = _DEFAULT_TARGET_LOGGERS,
) -> Iterator[PipelineRunContext]:
    """记录一次 per-symbol 管道执行，并捕获相关 logger 的日志尾部。"""
    ctx = PipelineRunContext()
    tail = _TailHandler()
    attached_loggers: list[logging.Logger] = []
    for name in target_loggers:
        lg = logging.getLogger(name)
        lg.addHandler(tail)
        attached_loggers.append(lg)

    started = time.monotonic()
    err: Optional[BaseException] = None
    try:
        yield ctx
    except BaseException as exc:  # noqa: BLE001 — we re-raise below
        err = exc
        ctx.status = "failed"
        if ctx.error_message is None:
            ctx.error_message = f"{type(exc).__name__}: {exc}"
    finally:
        duration_ms = int((time.monotonic() - started) * 1000)
        for lg in attached_loggers:
            try:
                lg.removeHandler(tail)
            except Exception:
                pass
        log_excerpt = tail.as_excerpt()
        if ctx.extra_log:
            log_excerpt = (log_excerpt + "\n" if log_excerpt else "") + ctx.extra_log
            log_excerpt = log_excerpt[-_MAX_LOG_CHARS:]

        try:
            with SessionLocal() as session:
                session.add(
                    PipelineRun(
                        symbol=symbol,
                        run_type=run_type,
                        status=ctx.status,
                        run_at=datetime.utcnow(),
                        duration_ms=duration_ms,
                        message=(ctx.message or None),
                        error_message=ctx.error_message,
                        log_excerpt=log_excerpt,
                        trigger=trigger,
                    )
                )
                session.commit()
        except Exception as persist_err:  # noqa: BLE001
            # 诊断表写入失败不应影响主流程
            logging.getLogger(__name__).debug(
                "persist pipeline_run failed (sym=%s type=%s): %s",
                symbol, run_type, persist_err,
            )

        if err is not None:
            raise err


def persist_pipeline_run(
    symbol: str,
    run_type: str,
    status: str,
    *,
    trigger: str = "scheduler",
    duration_ms: Optional[int] = None,
    message: Optional[str] = None,
    error_message: Optional[str] = None,
    log_excerpt: Optional[str] = None,
) -> None:
    """imperative API：直接写入一条 pipeline_runs。

    供无法方便使用 with 语句的场景（如既有 try/except/continue 循环体）调用。
    失败时静默吞掉异常，保证诊断落库不会劣化主流程。
    """
    payload = {
        "symbol": symbol,
        "run_type": run_type,
        "status": status,
        "run_at": datetime.utcnow(),
        "duration_ms": duration_ms,
        "message": message,
        "error_message": error_message,
        "log_excerpt": (log_excerpt[:_MAX_LOG_CHARS] if log_excerpt else None),
        "trigger": trigger,
    }
    try:
        with SessionLocal() as session:
            session.add(PipelineRun(**payload))
            session.commit()
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).debug(
            "persist_pipeline_run swallowed error (sym=%s type=%s status=%s): %s",
            symbol, run_type, status, exc,
        )


class TailCollector:
    """轻量包装 _TailHandler，供调用方手动 attach / detach / as_excerpt。"""

    def __init__(
        self,
        level: int = logging.INFO,
        max_chars: int = _MAX_LOG_CHARS,
        target_loggers: tuple[str, ...] = _DEFAULT_TARGET_LOGGERS,
    ) -> None:
        self._handler = _TailHandler(level=level, max_chars=max_chars)
        self._attached: list[logging.Logger] = []
        self._target_loggers = target_loggers

    def attach(self) -> "TailCollector":
        for name in self._target_loggers:
            lg = logging.getLogger(name)
            lg.addHandler(self._handler)
            self._attached.append(lg)
        return self

    def detach(self) -> None:
        for lg in self._attached:
            try:
                lg.removeHandler(self._handler)
            except Exception:
                pass
        self._attached = []

    def excerpt(self) -> Optional[str]:
        return self._handler.as_excerpt()


__all__ = [
    "record_pipeline_run",
    "PipelineRunContext",
    "persist_pipeline_run",
    "TailCollector",
]
