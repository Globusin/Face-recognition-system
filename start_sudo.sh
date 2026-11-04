#!/bin/bash

set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python"

cd "$PROJECT_DIR"

if [ ! -x "$VENV_PYTHON" ]; then
    echo "Не найдено виртуальное окружение: $VENV_PYTHON"
    exit 1
fi

# Проверяем, что setup.sh уже был запущен
if ! "$VENV_PYTHON" -c "import cv2, face_recognition, flask, psycopg, yaml, gunicorn" >/dev/null 2>&1; then
    echo "Не установлены зависимости"
    echo "Сначала запустите: ./setup.sh"
    exit 1
fi

if ! "$VENV_PYTHON" -c "from src.run_app import server_options; server_options()"; then
    echo "Проверьте TLS-файлы и сборку Vue. Подготовка: ./setup.sh"
    exit 1
fi

# Запрашиваем пароль до запуска фоновых процессов
if ! sudo -v; then
    echo "Не удалось получить права для запуска backend"
    exit 1
fi

# Запускаем PostgreSQL, если он ещё не работает
if ! systemctl is-active --quiet postgresql; then
    echo "Запуск PostgreSQL"
    if ! sudo systemctl start postgresql; then
        echo "Не удалось запустить PostgreSQL"
        exit 1
    fi
fi

# Создаём таблицы после запуска PostgreSQL
if ! "$VENV_PYTHON" utils/db_connect.py; then
    echo "Не удалось подключиться к PostgreSQL. Проверьте сервис и порт в config.yaml."
    exit 1
fi

# Один HTTPS-сервер отдаёт собранный Vue и API, Vite наружу не запускаем
exec sudo -n "$VENV_PYTHON" src/run_app.py
