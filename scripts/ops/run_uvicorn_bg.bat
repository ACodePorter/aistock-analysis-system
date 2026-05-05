@echo off
set ENABLE_SCHEDULER=0
set PYTHONPATH=backend
set WATCHLIST_FRESH_TTL=8
python -m uvicorn app.main:app --host 0.0.0.0 --port 8090 --log-level info
