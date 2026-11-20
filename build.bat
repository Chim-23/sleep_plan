@echo off
cd /d "%~dp0"
set "PY=%LocalAppData%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -m pip install -r requirements.txt -q
"%PY%" assets\generate_icon.py
"%PY%" -m PyInstaller --noconfirm SleepPlan.spec
echo.
if exist "dist\SleepPlan.exe" (
    echo 已生成: dist\SleepPlan.exe
) else (
    echo 构建失败，请检查上方错误信息。
)
pause