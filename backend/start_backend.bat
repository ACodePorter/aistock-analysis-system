@echo off
cd /d D:\workspace\mpj\aistock-full-project\backend
call conda activate ai_stock
python -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
