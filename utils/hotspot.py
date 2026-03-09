import subprocess
import re
import sys
import logging

from utils.logger import log_info, log_warning, log_error

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def start_hotspot(ssid, password):
    """
    Создает Wi-Fi хотспот с заданным SSID и паролем.
    
    Args:
        ssid (str): Имя сети Wi-Fi (SSID)
        password (str): Пароль для подключения к сети
    """
    try:
        log_info(f"Попытка создания Wi-Fi хотспота с SSID: {ssid}")
        
        # Останавливаем возможную предыдущую точку доступа
        log_info("Остановка предыдущей точки доступа (если существует)")
        result = subprocess.run(["nmcli", "connection", "down", "Hotspot"], check=False, capture_output=True, text=True)
        if result.returncode != 0:
            log_warning(f"Не удалось отключить предыдущую точку доступа: {result.stderr}")
        
        log_info("Получение интерфейса")
        ifname = get_wifi_interface_name()
        log_info("Получен интерфейс: " + ifname)

        # Запускаем точку доступа
        log_info("Запуск точки доступа")
        subprocess.run(["rfkill", "unblock", "wifi"], check=True)
        subprocess.run(["nmcli", "radio", "wifi", "on"], check=True)

        cmd = [
            "nmcli",
            "device",
            "wifi",
            "hotspot",
            "ifname", ifname,
            "ssid", ssid,
            "password", password
        ]

        log_info("Создание новой точки доступа")
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        log_info("Точка доступа создана успешно")

        log_info(f"Wi-Fi хотспот '{ssid}' успешно запущен")

    except subprocess.CalledProcessError as e:
        log_error(f"Ошибка при создании Wi-Fi хотспота: {e}")
        sys.exit(1)
    except Exception as e:
        log_error(f"Неожиданная ошибка: {e}")
        sys.exit(1)


def get_wifi_interface_name():
    output = subprocess.run(["nmcli", "device", "status"], check=True, capture_output=True, text=True)

    match = re.search(r'^(\S+)\s+wifi', output.stdout, re.MULTILINE)
    if match:
        wifi_device = match.group(1)
        return wifi_device
