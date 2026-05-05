@echo off
set ENABLE_SCHEDULER=0
set PYTHONPATH=backend
set WATCHLIST_FRESH_TTL=30
set LOCAL_CACHE_MAX=4096
python -m uvicorn app.main:app --host 127.0.0.1 --port 8081 --log-level info
