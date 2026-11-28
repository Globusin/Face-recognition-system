"""Единая точка вычисления корня проекта для путей к данным и конфигурации"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
