"""Display abstraction, state representations, and Raspberry Pi ST7735R implementation."""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from utils.logger import log_error, log_info, log_warning


class DisplayState(Enum):
    """Target system states for display according to AGENTS.md."""
    STANDBY = "standby"
    LOOK_AT_CAMERA = "look_at_camera"
    CHALLENGE = "challenge"
    CHECKING = "checking"
    ACCESS_GRANTED = "access_granted"
    ACCESS_DENIED = "access_denied"
    ERROR = "error"


# Visual formatting for each display state: (title/text, subtitle, foreground_color, background_color)
STATE_THEMES: Dict[DisplayState, Dict[str, Any]] = {
    DisplayState.STANDBY: {
        "title": "STANDBY",
        "subtitle": "Face Access",
        "fg": (200, 200, 200),
        "bg": (0, 0, 0),
        "accent": (50, 50, 100),
    },
    DisplayState.LOOK_AT_CAMERA: {
        "title": "LOOK AT",
        "subtitle": "CAMERA",
        "fg": (255, 255, 255),
        "bg": (0, 30, 70),
        "accent": (0, 150, 255),
    },
    DisplayState.CHALLENGE: {
        "title": "COMMAND",
        "subtitle": "",
        "fg": (255, 255, 0),
        "bg": (40, 40, 0),
        "accent": (255, 200, 0),
    },
    DisplayState.CHECKING: {
        "title": "CHECKING",
        "subtitle": "Please wait...",
        "fg": (255, 255, 255),
        "bg": (30, 30, 30),
        "accent": (100, 100, 255),
    },
    DisplayState.ACCESS_GRANTED: {
        "title": "ACCESS",
        "subtitle": "GRANTED",
        "fg": (255, 255, 255),
        "bg": (0, 80, 20),
        "accent": (0, 255, 100),
    },
    DisplayState.ACCESS_DENIED: {
        "title": "ACCESS",
        "subtitle": "DENIED",
        "fg": (255, 255, 255),
        "bg": (80, 0, 0),
        "accent": (255, 50, 50),
    },
    DisplayState.ERROR: {
        "title": "SYSTEM",
        "subtitle": "ERROR",
        "fg": (255, 255, 255),
        "bg": (60, 20, 0),
        "accent": (255, 100, 0),
    },
}


class Display(ABC):
    """Business-facing interface for a small local status display."""

    @abstractmethod
    def show_state(self, state: DisplayState, detail: Optional[str] = None) -> None:
        """Display a standard system state with optional detail text."""

    @abstractmethod
    def show_text(
        self,
        text: str,
        subtitle: Optional[str] = None,
        fg: Tuple[int, int, int] = (255, 255, 255),
        bg: Tuple[int, int, int] = (0, 0, 0),
    ) -> None:
        """Replace the display contents with text and optional subtitle."""

    @abstractmethod
    def clear(self) -> None:
        """Clear the display."""


class NullDisplay(Display):
    """No-op implementation for tests and hosts without TFT hardware."""

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
    """Render states and text to an ST7735R RGB display driver."""

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
            raise ValueError("Display dimensions must be positive")
        self._driver = driver
        self.width = driver.width
        self.height = driver.height
        self._foreground = foreground
        self._background = background
        self._font = ImageFont.load_default(size=font_size)
        self._small_font = ImageFont.load_default(size=small_font_size)

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
        """Initialize the ST7735R used on the Raspberry Pi stand."""
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
        """Render a system state screen with theme colors and borders."""
        theme = STATE_THEMES.get(state, STATE_THEMES[DisplayState.STANDBY])
        bg = theme["bg"]
        fg = theme["fg"]
        accent = theme.get("accent", fg)
        title = theme["title"]
        subtitle = detail if detail is not None else theme["subtitle"]

        image = Image.new("RGB", (self.width, self.height), bg)
        draw = ImageDraw.Draw(image)

        # Header / decorative border
        draw.rectangle((2, 2, self.width - 3, self.height - 3), outline=accent, width=2)
        draw.line((6, 32, self.width - 7, 32), fill=accent, width=1)

        # Status badge / title
        bbox = draw.textbbox((0, 0), title, font=self._font)
        t_w = bbox[2] - bbox[0]
        draw.text(((self.width - t_w) // 2, 10), title, font=self._font, fill=fg)

        # Subtitle / Details
        if subtitle:
            # Handle multi-line if needed
            lines = subtitle.split("\n")
            y_start = 55
            for line in lines[:4]:
                s_bbox = draw.textbbox((0, 0), line, font=self._small_font)
                s_w = s_bbox[2] - s_bbox[0]
                draw.text(((self.width - s_w) // 2, y_start), line, font=self._small_font, fill=fg)
                y_start += 16

        self._driver.image(image)

    def show_text(
        self,
        text: str,
        subtitle: Optional[str] = None,
        fg: Tuple[int, int, int] = (255, 255, 255),
        bg: Tuple[int, int, int] = (0, 0, 0),
    ) -> None:
        if not isinstance(text, str):
            raise TypeError("Display text must be a string")

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
    Factory function to initialize TFTDisplay or fallback to NullDisplay safely.
    Ensures hardware failures do not crash the host application.
    """
    if config is None:
        config = {}

    display_cfg = config.get("display", {})
    if not display_cfg.get("enabled", True):
        log_info("TFT Display disabled in configuration. Using NullDisplay.")
        return NullDisplay()

    try:
        cs_pin = display_cfg.get("cs_pin", "D5")
        dc_pin = display_cfg.get("dc_pin", "D25")
        rst_pin = display_cfg.get("rst_pin", "D24")
        width = display_cfg.get("width", 128)
        height = display_cfg.get("height", 160)
        rotation = display_cfg.get("rotation", 0)
        baudrate = display_cfg.get("baudrate", 16_000_000)

        log_info(f"Initializing TFTDisplay (ST7735R {width}x{height}, CS={cs_pin}, DC={dc_pin}, RST={rst_pin})...")
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
        log_info("TFT Display successfully initialized.")
        return display
    except Exception as e:
        log_warning(f"Could not initialize hardware TFTDisplay ({e}). Falling back to NullDisplay.")
        return NullDisplay()
