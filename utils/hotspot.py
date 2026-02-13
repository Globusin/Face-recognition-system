import subprocess
import re
import sys
import logging

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
        logging.info(f"Попытка создания Wi-Fi хотспота с SSID: {ssid}")
        
        # Останавливаем возможную предыдущую точку доступа
        logging.info("Остановка предыдущей точки доступа (если существует)")
        result = subprocess.run(["nmcli", "connection", "down", "Hotspot"], check=False, capture_output=True, text=True)
        if result.returncode != 0:
            logging.warning(f"Не удалось отключить предыдущую точку доступа: {result.stderr}")
        
        logging.info("Получение интерфейса")
        ifname = get_wifi_interface_name()
        logging.info("Получен интерфейс: " + ifname)

        cmd = [
            "nmcli",
            "connection",
            "add",
            "type", "wifi",
            "ifname", ifname,
            "con-name", "Hotspot",
            "autoconnect", "no",
            "wifi.mode", "ap",
            "wifi.ssid", ssid,
            "wifi.band", "bg",
            "ipv4.method", "shared",
            "ipv4.addresses", ""  # Не указываем шлюз - нет доступа к интернету
        ]
        logging.info("Создание новой точки доступа")
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        logging.info("Точка доступа создана успешно")

        # Устанавливаем пароль
        logging.info("Установка безопасности WPA-PSK")
        subprocess.run([
            "nmcli", "connection", "modify", "Hotspot",
            "wifi-sec.key-mgmt", "wpa-psk"
        ], check=True, capture_output=True, text=True)
        subprocess.run([
            "nmcli", "connection", "modify", "Hotspot",
            "wifi-sec.psk", password
        ], check=True, capture_output=True, text=True)
        logging.info("Пароль установлен")

        # Запускаем точку доступа
        logging.info("Запуск точки доступа")
        subprocess.run(["rfkill", "unblock", "wifi"], check=True)
        subprocess.run(["nmcli", "radio", "wifi", "on"], check=True)
        subprocess.run(["nmcli", "connection", "up", "Hotspot"], check=True, capture_output=True, text=True)
        logging.info(f"Wi-Fi хотспот '{ssid}' успешно запущен")

    except subprocess.CalledProcessError as e:
        logging.error(f"Ошибка при создании Wi-Fi хотспота: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Неожиданная ошибка: {e}")
        sys.exit(1)


def get_wifi_interface_name():
    output = subprocess.run(["nmcli", "device", "status"], check=True, capture_output=True, text=True)

    match = re.search(r'^(\S+)\s+wifi', output.stdout, re.MULTILINE)
    if match:
        wifi_device = match.group(1)
        return wifi_device