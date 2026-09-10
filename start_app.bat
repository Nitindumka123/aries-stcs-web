@echo off
cd C:\Users\dumka\OneDrive\Desktop\GUI\stcs_web
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --log-level info > app.log 2>&1
timeout /t 5 >nul