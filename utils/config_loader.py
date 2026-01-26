import yaml
import logging
from pathlib import Path

def load_config():
    """Загружает конфигурационный файл"""
    config_path = Path(__file__).parent.parent / 'config.yaml'
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as file:
            return yaml.safe_load(file)
    else:
        logging.warning(f"Конфигурационный файл {config_path} не найден, используются значения по умолчанию")
        return {}