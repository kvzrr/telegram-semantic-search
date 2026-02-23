@echo off
:: Устанавливаем кодировку UTF-8
chcp 65001 >nul
title Поиск по Telegram - Запуск
color 0A

echo ===================================================
echo   Semantic Search App: Запуск системы
echo ===================================================
echo.

:: 1. Проверка Python
echo [1/4] Проверка окружения
python --version >nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Python не найден!
    echo Пожалуйста, убедитесь, что Python установлен и добавлен в PATH.
    pause
    exit /b
)

:: 2. Переход в рабочую директорию
cd /d "%~dp0"

:: 3. Проверка и создание виртуального окружения
if not exist "venv\" (
    echo [2/4] Создание виртуального окружения
    python -m venv venv
    if errorlevel 1 (
        echo [ОШИБКА] Не удалось создать venv.
        pause
        exit /b
    )

    echo [3/4] Установка библиотек
    echo Это может занять время, пожалуйста, подождите...
    call venv\Scripts\activate
    python -m pip install --upgrade pip
    pip install -r requirements.txt
) else (
    echo [2/4] Виртуальное окружение найдено
    echo [3/4] Активация
    call venv\Scripts\activate
)

:: 4. Запуск приложения
echo [4/4] Запуск интерфейса
echo ---------------------------------------------------
echo ПРИЛОЖЕНИЕ ЗАПУЩЕНО.
echo НЕ ЗАКРЫВАЙТЕ ЭТО ОКНО ВО ВРЕМЯ РАБОТЫ.
echo ---------------------------------------------------
echo.

:: Запускаем streamlit
streamlit run source/app.py

:: Если произошла ошибка при работе
if errorlevel 1 (
    echo.
    echo [ОШИБКА] Произошел сбой при работе приложения.
    pause
)