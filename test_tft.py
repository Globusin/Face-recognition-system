#!/usr/bin/env python3

import time
import socket
import subprocess
from pathlib import Path

import board
import busio
import digitalio

from PIL import Image, ImageDraw, ImageFont, ImageOps
from adafruit_rgb_display.st7735 import ST7735R

from utils.config_loader import load_config


# ============================================================
# Настройки
# ============================================================

IMAGE_PATH = Path(
    "/home/pi/Face-recognition-system/assets/boot_image.png"
)

FONT_REGULAR = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
)

FONT_BOLD = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
)

# Nokia-подобный синий
BLUE = "#124191"

BACKGROUND = "white"


# ============================================================
# Получение IP
# ============================================================

def get_ip_address():
    """
    Возвращает первый нормальный IPv4-адрес устройства.
    """

    try:
        result = subprocess.check_output(
            ["hostname", "-I"],
            text=True
        ).strip()

        addresses = result.split()

        for address in addresses:
            # Нас интересует IPv4
            if "." in address and not address.startswith("127."):
                return address

    except Exception:
        pass

    return None


def wait_for_ip(timeout=20):
    """
    Ждём появления IP после загрузки Ubuntu.
    """

    start = time.time()

    while time.time() - start < timeout:
        ip = get_ip_address()

        if ip:
            return ip

        time.sleep(1)

    return "нет сети"


# ============================================================
# Шрифты
# ============================================================

def load_font(path, size):
    if Path(path).exists():
        return ImageFont.truetype(path, size)

    return ImageFont.load_default()


# ============================================================
# Работа с изображением
# ============================================================

def prepare_boot_image(path, width, height):
    """
    Подготавливает картинку для верхней части TFT.
    """

    image = Image.open(path).convert("RGB")

    # Вписываем в заданную область.
    image = ImageOps.contain(
        image,
        (width, height),
        method=Image.Resampling.LANCZOS
    )

    return image


# ============================================================
# TFT
# ============================================================

def create_display():

    config = load_config().get("display", {})

    spi = busio.SPI(
        clock=board.SCK,
        MOSI=board.MOSI
    )

    cs = digitalio.DigitalInOut(getattr(board, config.get("cs_pin", "D5")))
    dc = digitalio.DigitalInOut(getattr(board, config.get("dc_pin", "D25")))
    rst = digitalio.DigitalInOut(getattr(board, config.get("rst_pin", "D24")))

    display = ST7735R(
        spi,
        cs=cs,
        dc=dc,
        rst=rst,
        width=config.get("width", 128),
        height=config.get("height", 160),
        rotation=config.get("rotation", 0),
        baudrate=config.get("baudrate", 16000000),
        bgr=config.get("bgr", True)
    )

    return display


# ============================================================
# Рисование
# ============================================================

def draw_centered(draw, text, y, font, width, color):

    bbox = draw.textbbox(
        (0, 0),
        text,
        font=font
    )

    text_width = bbox[2] - bbox[0]

    x = (width - text_width) // 2

    draw.text(
        (x, y),
        text,
        font=font,
        fill=color
    )


def show_screen(display, ip_address):

    width = display.width
    height = display.height

    screen = Image.new(
        "RGB",
        (width, height),
        BACKGROUND
    )

    draw = ImageDraw.Draw(screen)

    # --------------------------------------------------------
    # Картинка
    # --------------------------------------------------------

    image_area_height = 120

    if IMAGE_PATH.exists():

        picture = prepare_boot_image(
            IMAGE_PATH,
            width,
            image_area_height
        )

        x = (width - picture.width) // 2
        y = (image_area_height - picture.height) // 2

        screen.paste(
            picture,
            (x, y)
        )

    else:
        error_font = load_font(
            FONT_REGULAR,
            10
        )

        draw_centered(
            draw,
            "Нет изображения",
            45,
            error_font,
            width,
            "red"
        )

    # --------------------------------------------------------
    # Домовой
    # --------------------------------------------------------

    title_font = load_font(
        FONT_BOLD,
        20
    )

    draw_centered(
        draw,
        "Домовой",
        105,
        title_font,
        width,
        BLUE
    )

    # --------------------------------------------------------
    # IP
    # --------------------------------------------------------

    ip_font = load_font(
        FONT_REGULAR,
        11
    )

    draw_centered(
        draw,
        f"IP: {ip_address}",
        137,
        ip_font,
        width,
        BLUE
    )

    # Отправляем готовый кадр на TFT
    display.image(screen)


# ============================================================
# main
# ============================================================

def main():

    print("Инициализация ST7735R...")

    display = create_display()

    print(
        f"Дисплей: "
        f"{display.width}x{display.height}"
    )

    print("Ожидание IP-адреса...")

    ip_address = wait_for_ip(
        timeout=20
    )

    print(
        f"IP: {ip_address}"
    )

    show_screen(
        display,
        ip_address
    )

    print(
        "Экран приветствия отображён."
    )


if __name__ == "__main__":
    main()