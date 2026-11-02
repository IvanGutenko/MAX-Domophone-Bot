@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist "venv\Scripts\activate.bat" (
    call "venv\Scripts\activate.bat"
)

echo Запуск бота...
python -m bot.main 2> error_log.txt

echo.
echo === ТЕКСТ ОШИБКИ ===
type error_log.txt
echo ====================
echo.
pause
cmd /k
