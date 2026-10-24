#!/usr/bin/env python3

import time
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

PROJECT_DIR = Path(__file__).resolve().parent
IMAGE_DIR = PROJECT_DIR / "resources" / "display-images"

FACE_IMAGES = {
    "chill": IMAGE_DIR / "display-face-chill.png",
    "front": IMAGE_DIR / "display-face-front.png",
    "left": IMAGE_DIR / "display-face-left.png",
    "right": IMAGE_DIR / "display-face-right.png",
    "smile": IMAGE_DIR / "display-face-smile.png",
}

DEFAULT_FACE = "chill"
FACE_SEQUENCE = (
    "chill",
    "front",
    "left",
    "front",
    "right",
    "front",
    "smile",
    "front",
)
FRAME_DELAY = 1

FONT_REGULAR = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
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

def prepare_face_image(path, width, height):
    """
    Подготавливает изображение лица для TFT
    """

    with Image.open(path) as source:
        image = source.convert("RGB")

    # Заполняем всю область и не растягиваем картинку
    image = ImageOps.fit(
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

def draw_centered(
    draw,
    text,
    y,
    font,
    width,
    color,
    stroke_width=0,
    stroke_fill=None
):

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
        fill=color,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill
    )


def create_screen(display, ip_address, face_name=DEFAULT_FACE):

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

    image_path = FACE_IMAGES.get(face_name, FACE_IMAGES[DEFAULT_FACE])

    if image_path.exists():

        picture = prepare_face_image(
            image_path,
            width,
            height
        )

        screen.paste(
            picture,
            (0, 0)
        )

    else:
        error_font = load_font(
            FONT_REGULAR,
            10
        )

        draw_centered(
            draw,
            "Нет изображения",
            height // 2,
            error_font,
            width,
            "red"
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
        height - 17,
        ip_font,
        width,
        "white",
        stroke_width=2,
        stroke_fill=BLUE
    )

    return screen


def show_animation(display, ip_address):
    # Готовим кадры один раз перед запуском анимации
    frames = {
        face_name: create_screen(display, ip_address, face_name)
        for face_name in FACE_IMAGES
    }

    while True:
        for face_name in FACE_SEQUENCE:
            display.image(frames[face_name])
            time.sleep(FRAME_DELAY)


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

    print("Анимация запущена. Для остановки нажмите Ctrl+C")

    try:
        show_animation(display, ip_address)
    except KeyboardInterrupt:
        print("\nАнимация остановлена")


if __name__ == "__main__":
    main()
