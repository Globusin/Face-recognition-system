#!/bin/bash

# Путь к вашему виртуальному окружению
VENV_PATH="venv"

# Активируем окружение и запускаем с sudo
source $VENV_PATH/bin/activate
sudo -E env PATH=$PATH:$VENV_PATH/bin python3 src/run_app.py
sudo -E env PATH=$PATH:$VENV_PATH/bin python3 utils/db_connect.py
