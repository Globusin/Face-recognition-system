#!/bin/bash

# Путь к вашему виртуальному окружению
VENV_PATH="venv"

# Активируем окружение и запускаем с sudo
source $VENV_PATH/bin/activate

# Запускаем основное приложение
sudo -E env PATH=$PATH:$VENV_PATH/bin python3 src/run_app.py &
APP_PID=$!

# Запускаем мониторинг камеры в фоновом режиме
sudo -E env PATH=$PATH:$VENV_PATH/bin python3 src/monitor.py &
MONITOR_PID=$!

# Запускаем подключение к БД
sudo -E env PATH=$PATH:$VENV_PATH/bin python3 utils/db_connect.py &
DB_PID=$!

# Функция для корректного завершения всех процессов
cleanup() {
    echo "Завершение работы..."
    kill $APP_PID $MONITOR_PID $DB_PID 2>/dev/null
    wait
    exit 0
}

# Перехват сигналов завершения
trap cleanup SIGINT SIGTERM

# Ожидаем завершения всех процессов
wait
