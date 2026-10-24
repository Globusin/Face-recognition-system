#!/bin/bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/venv"
VENV_PYTHON="$VENV_DIR/bin/python"
FRONTEND_DIR="$PROJECT_DIR/Face-Recognition-Vue"

show_error() {
    echo "Ошибка на строке $1"
    echo "Исправьте ошибку и запустите setup.sh ещё раз"
}

trap 'show_error "$LINENO"' ERR

if [ "${EUID}" -eq 0 ]; then
    echo "Запускайте скрипт без sudo: ./setup.sh"
    exit 1
fi

if [ ! -f "$PROJECT_DIR/config.yaml" ]; then
    echo "Не найден config.yaml"
    exit 1
fi

if [ ! -f /etc/os-release ]; then
    echo "Не удалось определить операционную систему"
    exit 1
fi

. /etc/os-release

if [ "${ID:-}" != "ubuntu" ]; then
    echo "Скрипт рассчитан на Ubuntu"
    exit 1
fi

echo "Ubuntu ${VERSION_ID:-unknown}, архитектура $(uname -m)"

# Сохраняем права sudo на время установки
sudo -v

echo "Установка системных пакетов"
sudo apt-get update
sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y \
    build-essential \
    ca-certificates \
    cmake \
    git \
    gpiod \
    libgpiod-dev \
    libjpeg-dev \
    liblapack-dev \
    libopenblas-dev \
    libpng-dev \
    nodejs \
    npm \
    pkg-config \
    postgresql \
    postgresql-contrib \
    python3 \
    python3-dev \
    python3-venv \
    v4l-utils

SYSTEM_PYTHON_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
VENV_PYTHON_VERSION=""

if [ -x "$VENV_PYTHON" ]; then
    VENV_PYTHON_VERSION="$($VENV_PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
fi

if [ "$VENV_PYTHON_VERSION" != "$SYSTEM_PYTHON_VERSION" ]; then
    echo "Создание виртуального окружения Python"
    python3 -m venv --clear "$VENV_DIR"
fi

echo "Установка Python-зависимостей"
"$VENV_PYTHON" -m pip install --disable-pip-version-check --upgrade pip wheel
"$VENV_PYTHON" -m pip install --disable-pip-version-check -r "$PROJECT_DIR/requirements.txt"

mapfile -t DB_SETTINGS < <(
    "$VENV_PYTHON" - "$PROJECT_DIR/config.yaml" <<'PY'
import sys
import yaml

with open(sys.argv[1], encoding="utf-8") as config_file:
    database = yaml.safe_load(config_file).get("database", {})

print(database.get("host", "localhost"))
print(database.get("port", 5433))
print(database.get("name", "face-recognition"))
print(database.get("user", "postgres"))
print(database.get("password", ""))
PY
)

DB_HOST="${DB_SETTINGS[0]}"
DB_PORT="${DB_SETTINGS[1]}"
DB_NAME="${DB_SETTINGS[2]}"

if [ "$DB_HOST" != "localhost" ] && [ "$DB_HOST" != "127.0.0.1" ]; then
    echo "setup.sh поддерживает только локальную PostgreSQL"
    exit 1
fi

CLUSTER_INFO="$(
    pg_lsclusters --no-header | awk -v port="$DB_PORT" '$3 == port {print $1, $2; exit}'
)"

if [ -z "$CLUSTER_INFO" ]; then
    CLUSTER_INFO="$(pg_lsclusters --no-header | awk 'NR == 1 {print $1, $2}')"
fi

read -r PG_VERSION PG_CLUSTER <<< "$CLUSTER_INFO"

if [ -z "${PG_VERSION:-}" ] || [ -z "${PG_CLUSTER:-}" ]; then
    echo "Не найден кластер PostgreSQL"
    exit 1
fi

PGVECTOR_PACKAGE="postgresql-${PG_VERSION}-pgvector"

PGVECTOR_INSTALLED=false
if dpkg-query -W -f='${Status}' "$PGVECTOR_PACKAGE" 2>/dev/null | grep -q "install ok installed"; then
    PGVECTOR_INSTALLED=true
fi

if [ "$PGVECTOR_INSTALLED" = false ] && ! apt-cache show "$PGVECTOR_PACKAGE" >/dev/null 2>&1; then
    echo "Не найден пакет $PGVECTOR_PACKAGE"
    echo "Проверьте, что для Ubuntu включён репозиторий universe"
    exit 1
fi

if [ "$PGVECTOR_INSTALLED" = false ]; then
    echo "Установка pgvector для PostgreSQL $PG_VERSION"
    sudo apt-get install -y "$PGVECTOR_PACKAGE"
fi

echo "Настройка PostgreSQL на порту $DB_PORT"
sudo pg_conftool "$PG_VERSION" "$PG_CLUSTER" set port "$DB_PORT"
sudo systemctl enable postgresql
sudo systemctl restart postgresql

if ! pg_isready --host localhost --port "$DB_PORT" >/dev/null; then
    echo "PostgreSQL не отвечает на порту $DB_PORT"
    exit 1
fi

echo "Создание пользователя и базы данных"
"$VENV_PYTHON" - "$PROJECT_DIR/config.yaml" <<'PY' | \
    sudo -u postgres psql --port "$DB_PORT" --dbname postgres --set ON_ERROR_STOP=1
import sys

import yaml

with open(sys.argv[1], encoding="utf-8") as config_file:
    database = yaml.safe_load(config_file).get("database", {})

database_name = str(database.get("name", "face-recognition"))
database_user = str(database.get("user", "postgres"))
database_password = str(database.get("password", ""))

def sql_text(value):
    return "'" + value.replace("'", "''") + "'"


def sql_name(value):
    return '"' + value.replace('"', '""') + '"'


print(
    "SELECT format('CREATE ROLE %I LOGIN', {user}) "
    "WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = {user});"
    .format(user=sql_text(database_user))
)
print("\\gexec")
print(
    "ALTER ROLE {user} PASSWORD {password};".format(
        user=sql_name(database_user),
        password=sql_text(database_password),
    )
)
print(
    "SELECT format('CREATE DATABASE %I OWNER %I', {name}, {user}) "
    "WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = {name});"
    .format(name=sql_text(database_name), user=sql_text(database_user))
)
print("\\gexec")
PY

sudo -u postgres psql \
    --port "$DB_PORT" \
    --dbname "$DB_NAME" \
    --set ON_ERROR_STOP=1 \
    --command "CREATE EXTENSION IF NOT EXISTS vector"

echo "Создание таблиц"
cd "$PROJECT_DIR"
"$VENV_PYTHON" utils/db_connect.py

if [ -f "$FRONTEND_DIR/package-lock.json" ]; then
    if ! node -e '
        const [major, minor] = process.versions.node.split(".").map(Number)
        const supported = (major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major > 22
        process.exit(supported ? 0 : 1)
    '; then
        echo "Для Vue нужен Node.js 20.19 или 22.12 и новее"
        echo "Установленная версия: $(node --version)"
        exit 1
    fi

    echo "Установка Vue-зависимостей"
    npm --prefix "$FRONTEND_DIR" ci

    echo "Проверка сборки Vue"
    npm --prefix "$FRONTEND_DIR" run build
fi

# Даём пользователю доступ к камерам и аппаратным интерфейсам
for group in video gpio spi; do
    if getent group "$group" >/dev/null; then
        sudo usermod -aG "$group" "$USER"
    fi
done

echo
echo "Установка завершена"
echo "Запуск backend: ./start_sudo.sh"
echo "Запуск Vue: npm --prefix Face-Recognition-Vue run dev -- --host 0.0.0.0"

if [ ! -e /dev/spidev0.0 ]; then
    echo "SPI пока недоступен, TFT нужно проверить отдельно"
fi
