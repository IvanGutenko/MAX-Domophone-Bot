@echo off
chcp 65001 >nul

:: Переходим в папку скрипта, используя кавычки для путей с пробелами
cd /d "%~dp0"

:: Проверка наличия файла бота без использования блока ( )
if not exist "bot\main.py" goto :error_no_bot

:: Активация виртуального окружения
if exist "venv\Scripts\activate.bat" (
    call "venv\Scripts\activate.bat"
)

:: Запуск бота
echo Запуск бота...
python -m bot.main

if %ERRORLEVEL% neq 0 (
    echo.
    echo Бот завершил работу с ошибкой (код %ERRORLEVEL%).
    pause
)
exit /b 0

:error_no_bot
echo.
echo ОШИБКА: Файл bot\main.py не найден. 
echo Текущая папка: %CD%
echo Проверьте, что вы запускаете файл из правильной папки.
echo.
pause
exit /b 1
