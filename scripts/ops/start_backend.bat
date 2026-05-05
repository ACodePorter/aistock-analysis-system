@echo off
REM === AIStock 后端启动脚本（进程隔离架构） ===
REM API 进程: 只处理 HTTP 请求，不运行调度器
REM Worker 进程: 只运行调度器和后台任务，不暴露端口
REM
REM 用法:
REM   start_backend.bat          — 同时启动 API + Worker
REM   start_backend.bat api      — 只启动 API
REM   start_backend.bat worker   — 只启动 Worker
REM   start_backend.bat legacy   — 旧模式（API+调度器同进程，不推荐）

cd /d D:\workspace\mpj\aistock-full-project\backend
call conda activate ai_stock

if "%1"=="api" goto :api
if "%1"=="worker" goto :worker
if "%1"=="legacy" goto :legacy

REM 默认: 同时启动 API + Worker（两个窗口）
echo [AIStock] 启动 API 进程（ENABLE_SCHEDULER=0）...
start "AIStock-API" cmd /k "cd /d D:\workspace\mpj\aistock-full-project\backend && conda activate ai_stock && set ENABLE_SCHEDULER=0 && python -m uvicorn app.main:app --host 0.0.0.0 --port 8081 --reload"

echo [AIStock] 启动 Worker 进程...
start "AIStock-Worker" cmd /k "cd /d D:\workspace\mpj\aistock-full-project\backend && conda activate ai_stock && set ENABLE_SCHEDULER=1 && python -m app.worker"

echo [AIStock] API + Worker 已在独立窗口中启动
goto :eof

:api
set ENABLE_SCHEDULER=0
echo [AIStock] 启动 API 进程（不含调度器）...
python -m uvicorn app.main:app --host 0.0.0.0 --port 8081 --reload
goto :eof

:worker
set ENABLE_SCHEDULER=1
echo [AIStock] 启动 Worker 进程（不含 API）...
python -m app.worker
goto :eof

:legacy
set ENABLE_SCHEDULER=1
echo [AIStock] 旧模式启动（API + 调度器同进程，不推荐）...
python -m uvicorn app.main:app --host 0.0.0.0 --port 8081 --reload
goto :eof
