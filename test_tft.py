import board
import busio
import digitalio
from PIL import Image, ImageDraw, ImageFont

from adafruit_rgb_display.st7735 import ST7735R


spi = busio.SPI(
    clock=board.SCK,
    MOSI=board.MOSI
)

cs = digitalio.DigitalInOut(board.D5)   # GPIO5, pin 29
dc = digitalio.DigitalInOut(board.D25)   # GPIO25, pin 22
rst = digitalio.DigitalInOut(board.D24)  # GPIO24, pin 18

display = ST7735R(
    spi,
    cs=cs,
    dc=dc,
    rst=rst,
    width=128,
    height=160,
    rotation=0,
    baudrate=16000000
)

image = Image.new("RGB", (display.width, display.height), "black")
draw = ImageDraw.Draw(image)
font = ImageFont.load_default(size=24)

bbox = draw.textbbox((0, 0), "Hello", font=font)
text_width = bbox[2] - bbox[0]
text_height = bbox[3] - bbox[1]
position = (
    (display.width - text_width) // 2,
    (display.height - text_height) // 2,
)

draw.text(position, "Hello", font=font, fill="white")
display.image(image)
