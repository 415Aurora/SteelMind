@echo off
if "%PORT%"=="" set PORT=8000
python -m uvicorn steelmind_export.api:app --host 127.0.0.1 --port %PORT%
