import yaml

from utils.paths import PROJECT_ROOT


def load_config():
    """Загружает конфигурационный файл"""
    config_path = PROJECT_ROOT / 'config.yaml'
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as file:
            return yaml.safe_load(file)
    else:
        return {}
