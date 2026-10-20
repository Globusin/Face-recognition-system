"""Состояния экрана и работа с TFT-дисплеем ST7735R на Raspberry Pi"""

import time
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageOps

from utils.logger import log_error, log_info, log_warning


class DisplayState(Enum):
    """Состояния системы для вывода на экран"""
    STANDBY = "standby"
    LOOK_AT_CAMERA = "look_at_camera"
    CHALLENGE = "challenge"
    CHECKING = "checking"
    ACCESS_GRANTED = "access_granted"
    ACCESS_DENIED = "access_denied"
    ERROR = "error"


PROJECT_DIR = Path(__file__).resolve().parent.parent
DISPLAY_IMAGE_DIR = PROJECT_DIR / "resources" / "display-images"

STATE_IMAGES = {
    DisplayState.ERROR: (
        DISPLAY_IMAGE_DIR / "display-face-error.png",
    ),
    DisplayState.ACCESS_GRANTED: (
        DISPLAY_IMAGE_DIR / "display-face-welcome.png",
    ),
    DisplayState.ACCESS_DENIED: (
        DISPLAY_IMAGE_DIR / "display-face-refusal-1.png",
        DISPLAY_IMAGE_DIR / "display-face-refusal-2.png",
    ),
}

STATE_CAPTIONS = {
    DisplayState.ERROR: "ОШИБКА\nСИСТЕМЫ",
    DisplayState.ACCESS_GRANTED: "ДОБРО\nПОЖАЛОВАТЬ",
    DisplayState.ACCESS_DENIED: "ДОСТУП\nЗАПРЕЩЁН",
}

DENIED_FRAME_DELAY = 0.2
DENIED_ANIMATION_REPEATS = 2


# Заголовки, подписи и цвета для каждого состояния
STATE_THEMES: Dict[DisplayState, Dict[str, Any]] = {
    DisplayState.STANDBY: {
        "title": "ОЖИДАНИЕ",
        "subtitle": "Подойдите к камере",
        "fg": (200, 200, 200),
        "bg": (0, 0, 0),
        "accent": (50, 50, 100),
    },
    DisplayState.LOOK_AT_CAMERA: {
        "title": "СМОТРИТЕ",
        "subtitle": "В камеру",
        "fg": (255, 255, 255),
        "bg": (0, 30, 70),
        "accent": (0, 150, 255),
    },
    DisplayState.CHALLENGE: {
        "title": "ЗАДАНИЕ",
        "subtitle": "",
        "fg": (255, 255, 0),
        "bg": (40, 40, 0),
        "accent": (255, 200, 0),
    },
    DisplayState.CHECKING: {
        "title": "ПРОВЕРКА",
        "subtitle": "Подождите",
        "fg": (255, 255, 255),
        "bg": (30, 30, 30),
        "accent": (100, 100, 255),
    },
    DisplayState.ACCESS_GRANTED: {
        "title": "ДОСТУП",
        "subtitle": "Разрешён",
        "fg": (255, 255, 255),
        "bg": (0, 80, 20),
        "accent": (0, 255, 100),
    },
    DisplayState.ACCESS_DENIED: {
        "title": "ДОСТУП",
        "subtitle": "Запрещён",
        "fg": (255, 255, 255),
        "bg": (80, 0, 0),
        "accent": (255, 50, 50),
    },
    DisplayState.ERROR: {
        "title": "ОШИБКА",
        "subtitle": "Проверьте систему",
        "fg": (255, 255, 255),
        "bg": (60, 20, 0),
        "accent": (255, 100, 0),
    },
}


class Display(ABC):
    """Общий интерфейс экрана для остальных частей программы"""

    @abstractmethod
    def show_state(self, state: DisplayState, detail: Optional[str] = None) -> None:
        """Показывает состояние системы и дополнительную подпись"""

    @abstractmethod
    def show_text(
        self,
        text: str,
        subtitle: Optional[str] = None,
        fg: Tuple[int, int, int] = (255, 255, 255),
        bg: Tuple[int, int, int] = (0, 0, 0),
    ) -> None:
        """Показывает текст и дополнительную подпись"""

    @abstractmethod
    def clear(self) -> None:
        """Очищает экран"""


class NullDisplay(Display):
    """Заглушка для тестов и запуска без физического экрана"""

    def show_state(self, state: DisplayState, detail: Optional[str] = None) -> None:
        pass

    def show_text(
        self,
        text: str,
        subtitle: Optional[str] = None,
        fg: Tuple[int, int, int] = (255, 255, 255),
        bg: Tuple[int, int, int] = (0, 0, 0),
    ) -> None:
        pass

    def clear(self) -> None:
        pass


class TFTDisplay(Display):
    """Выводит состояния, изображения и текст на дисплей ST7735R"""

    def __init__(
        self,
        driver: Any,
        *,
        font_size: int = 18,
        small_font_size: int = 12,
        foreground: Tuple[int, int, int] = (255, 255, 255),
        background: Tuple[int, int, int] = (0, 0, 0),
    ) -> None:
        if driver.width <= 0 or driver.height <= 0:
            raise ValueError("Размеры дисплея должны быть больше нуля")
        self._driver = driver
        self.width = driver.width
        self.height = driver.height
        self._foreground = foreground
        self._background = background
        # Этот шрифт поддерживает русские буквы
        self._font = self._load_caption_font(font_size)
        self._small_font = self._load_caption_font(small_font_size)
        self._caption_font = self._load_caption_font(small_font_size)
        self._image_frames = self._load_image_frames()

    @staticmethod
    def _load_caption_font(size):
        font_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
        if font_path.exists():
            return ImageFont.truetype(font_path, size)
        return ImageFont.load_default(size=size)

    def _load_image_frames(self):
        frames = {}

        for state, paths in STATE_IMAGES.items():
            state_frames = []
            for path in paths:
                try:
                    with Image.open(path) as source:
                        image = ImageOps.fit(
                            source.convert("RGB"),
                            (self.width, self.height),
                            method=Image.Resampling.LANCZOS,
                        )
                    self._draw_caption(image, STATE_CAPTIONS[state])
                    state_frames.append(image)
                except OSError as error:
                    log_warning(f"Не удалось загрузить изображение TFT '{path}': {error}")

            if state_frames:
                frames[state] = state_frames

        return frames

    def _draw_caption(self, image, caption):
        draw = ImageDraw.Draw(image)
        lines = caption.splitlines()
        line_height = self._caption_font.size + 1
        y = self.height - line_height * len(lines) - 7

        for line in lines:
            box = draw.textbbox((0, 0), line, font=self._caption_font, stroke_width=1)
            text_width = box[2] - box[0]
            draw.text(
                ((self.width - text_width) // 2, y),
                line,
                font=self._caption_font,
                fill=(255, 255, 255),
                stroke_width=2,
                stroke_fill=(0, 0, 0),
            )
            y += line_height

    @classmethod
    def from_raspberry_pi(
        cls,
        *,
        cs_pin: str = "D5",
        dc_pin: str = "D25",
        rst_pin: str = "D24",
        width: int = 128,
        height: int = 160,
        rotation: int = 0,
        baudrate: int = 16_000_000,
        bgr: bool = True,
        font_size: int = 18,
        small_font_size: int = 12,
    ) -> "TFTDisplay":
        """Подключает дисплей ST7735R к Raspberry Pi"""
        import board
        import busio
        import digitalio
        from adafruit_rgb_display.st7735 import ST7735R

        spi = busio.SPI(clock=board.SCK, MOSI=board.MOSI)
        driver = ST7735R(
            spi,
            cs=digitalio.DigitalInOut(getattr(board, cs_pin)),
            dc=digitalio.DigitalInOut(getattr(board, dc_pin)),
            rst=digitalio.DigitalInOut(getattr(board, rst_pin)),
            width=width,
            height=height,
            rotation=rotation,
            baudrate=baudrate,
            bgr=bgr,
        )
        return cls(
            driver,
            font_size=font_size,
            small_font_size=small_font_size,
        )

    def show_state(self, state: DisplayState, detail: Optional[str] = None) -> None:
        """Показывает изображение состояния или текстовый экран"""
        if self._show_image_state(state):
            return

        theme = STATE_THEMES.get(state, STATE_THEMES[DisplayState.STANDBY])
        bg = theme["bg"]
        fg = theme["fg"]
        accent = theme.get("accent", fg)
        title = theme["title"]
        subtitle = detail if detail is not None else theme["subtitle"]

        image = Image.new("RGB", (self.width, self.height), bg)
        draw = ImageDraw.Draw(image)

        # Рамка экрана и линия под заголовком
        draw.rectangle((2, 2, self.width - 3, self.height - 3), outline=accent, width=2)
        draw.line((6, 32, self.width - 7, 32), fill=accent, width=1)

        # Заголовок состояния
        bbox = draw.textbbox((0, 0), title, font=self._font)
        t_w = bbox[2] - bbox[0]
        draw.text(((self.width - t_w) // 2, 10), title, font=self._font, fill=fg)

        # Дополнительная подпись
        if subtitle:
            # Показываем не больше четырёх строк
            lines = subtitle.split("\n")
            y_start = 55
            for line in lines[:4]:
                s_bbox = draw.textbbox((0, 0), line, font=self._small_font)
                s_w = s_bbox[2] - s_bbox[0]
                draw.text(((self.width - s_w) // 2, y_start), line, font=self._small_font, fill=fg)
                y_start += 16

        self._driver.image(image)

    def _show_image_state(self, state):
        frames = self._image_frames.get(state)
        if not frames:
            return False

        if state == DisplayState.ACCESS_DENIED:
            for _ in range(DENIED_ANIMATION_REPEATS):
                for frame in frames:
                    self._driver.image(frame)
                    time.sleep(DENIED_FRAME_DELAY)
        else:
            self._driver.image(frames[0])

        return True

    def show_text(
        self,
        text: str,
        subtitle: Optional[str] = None,
        fg: Tuple[int, int, int] = (255, 255, 255),
        bg: Tuple[int, int, int] = (0, 0, 0),
    ) -> None:
        if not isinstance(text, str):
            raise TypeError("Текст для дисплея должен быть строкой")

        image = Image.new("RGB", (self.width, self.height), bg)
        draw = ImageDraw.Draw(image)

        bbox = draw.textbbox((0, 0), text, font=self._font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        y_offset = (self.height - text_height) // 2 if not subtitle else (self.height // 3)
        draw.text(((self.width - text_width) // 2, y_offset), text, font=self._font, fill=fg)

        if subtitle:
            s_bbox = draw.textbbox((0, 0), subtitle, font=self._small_font)
            s_w = s_bbox[2] - s_bbox[0]
            draw.text(((self.width - s_w) // 2, y_offset + text_height + 12), subtitle, font=self._small_font, fill=fg)

        self._driver.image(image)

    def clear(self) -> None:
        image = Image.new("RGB", (self.width, self.height), self._background)
        self._driver.image(image)


def initialize_display(config: Optional[Dict[str, Any]] = None) -> Display:
    """
    Подключает TFT-дисплей или возвращает заглушку при ошибке
    Ошибка экрана не останавливает основную программу
    """
    if config is None:
        config = {}

    display_cfg = config.get("display", {})
    if not display_cfg.get("enabled", True):
        log_info("TFT-дисплей отключён в настройках, используется заглушка")
        return NullDisplay()

    try:
        cs_pin = display_cfg.get("cs_pin", "D5")
        dc_pin = display_cfg.get("dc_pin", "D25")
        rst_pin = display_cfg.get("rst_pin", "D24")
        width = display_cfg.get("width", 128)
        height = display_cfg.get("height", 160)
        rotation = display_cfg.get("rotation", 0)
        baudrate = display_cfg.get("baudrate", 16_000_000)

        log_info(f"Подключение TFT-дисплея ST7735R {width}x{height}, CS={cs_pin}, DC={dc_pin}, RST={rst_pin}")
        display = TFTDisplay.from_raspberry_pi(
            cs_pin=cs_pin,
            dc_pin=dc_pin,
            rst_pin=rst_pin,
            width=width,
            height=height,
            rotation=rotation,
            baudrate=baudrate,
        )
        display.show_state(DisplayState.STANDBY)
        log_info("TFT-дисплей подключён")
        return display
    except Exception as e:
        log_warning(f"Не удалось подключить TFT-дисплей ({e}), используется заглушка")
        return NullDisplay()
