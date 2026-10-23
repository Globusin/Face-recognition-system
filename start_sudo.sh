#!/bin/bash

set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python"
FRONTEND_DIR="$PROJECT_DIR/Face-Recognition-Vue"
VITE="$FRONTEND_DIR/node_modules/.bin/vite"

cd "$PROJECT_DIR"

if [ ! -x "$VENV_PYTHON" ]; then
    echo "Не найдено виртуальное окружение: $VENV_PYTHON"
    exit 1
fi

# Проверяем, что setup.sh уже был запущен
if ! "$VENV_PYTHON" -c "import cv2, face_recognition, flask, psycopg, yaml" >/dev/null 2>&1; then
    echo "Не установлены зависимости"
    echo "Сначала запустите: ./setup.sh"
    exit 1
fi

if [ ! -x "$VITE" ]; then
    echo "Не установлены зависимости Vue"
    echo "Сначала запустите: ./setup.sh"
    exit 1
fi

if ! node -e '
    const [major, minor] = process.versions.node.split(".").map(Number)
    const supported = (major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major > 22
    process.exit(supported ? 0 : 1)
' 2>/dev/null; then
    echo "Для Vue нужен Node.js 20.19 или 22.12 и новее"
    echo "Запустите: ./setup.sh"
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

sudo "$VENV_PYTHON" src/run_app.py &
APP_PID=$!

# Запускаем Vue от обычного пользователя
(
    cd "$FRONTEND_DIR"
    exec "$VITE" --host 0.0.0.0
) &
FRONTEND_PID=$!

# Функция для корректного завершения всех процессов
cleanup() {
    echo "Завершение работы..."
    kill "$APP_PID" "$FRONTEND_PID" 2>/dev/null
    wait "$APP_PID" "$FRONTEND_PID" 2>/dev/null
}

# Перехват сигналов завершения
trap 'cleanup; exit 0' SIGINT SIGTERM

# Если один процесс завершился, останавливаем второй
wait -n "$APP_PID" "$FRONTEND_PID"
EXIT_CODE=$?
cleanup
exit "$EXIT_CODE"
