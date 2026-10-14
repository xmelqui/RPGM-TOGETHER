"""Builds the app icon ("dream door") as pixel art: rpgmt/assets/rpgmt.ico + PNGs.

Usage: .venv\\Scripts\\python tools\\make_icon.py
A hand-drawn 16x16 version is used for small sizes; bigger sizes are exact
pixel upscales (no blur) of the 16 or 32 px drawings.
"""
import pathlib

from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "rpgmt" / "assets"

CLEAR = (0, 0, 0, 0)
NIGHT = (30, 16, 46, 255)        # background circle
RIM = (98, 58, 140, 255)         # lighter ring so it shows on dark taskbars
DOOR = (120, 62, 164, 255)
DOOR_LIGHT = (196, 136, 236, 255)
DOOR_DARK = (74, 34, 104, 255)
KNOB = (255, 214, 102, 255)
FLOOR = (14, 8, 22, 255)
WHITE = (255, 255, 255, 255)
DOT = (30, 16, 46, 255)


def door_32():
    img = Image.new("RGBA", (32, 32), CLEAR)
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, 31, 31), fill=RIM)
    d.ellipse((1, 1, 30, 30), fill=NIGHT)
    d.rectangle((8, 9, 19, 28), fill=DOOR)                 # door
    d.line((8, 9, 19, 9), fill=DOOR_LIGHT)                 # lit top + left edge
    d.line((8, 9, 8, 28), fill=DOOR_LIGHT)
    d.line((19, 10, 19, 28), fill=DOOR_DARK)               # shaded right edge
    d.rectangle((10, 11, 17, 18), fill=DOOR_DARK)          # panels
    d.rectangle((10, 21, 17, 26), fill=DOOR_DARK)
    d.rectangle((16, 19, 17, 20), fill=KNOB)               # knob
    d.rectangle((5, 28, 23, 29), fill=FLOOR)               # floor shadow
    # speech bubble with "..."
    d.rectangle((18, 2, 29, 9), fill=WHITE)
    for x, y in ((18, 2), (29, 2), (18, 9), (29, 9)):
        d.point((x, y), fill=NIGHT)
    d.rectangle((19, 10, 21, 10), fill=WHITE)
    d.point((19, 11), fill=WHITE)
    for x in (20, 23, 26):
        d.rectangle((x, 5, x + 1, 6), fill=DOT)
    return img


def door_16():
    """Drawn for 16 px: fewer, bolder pixels."""
    img = Image.new("RGBA", (16, 16), CLEAR)
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, 15, 15), fill=RIM)
    d.ellipse((1, 1, 14, 14), fill=NIGHT)
    d.rectangle((4, 5, 9, 14), fill=DOOR)
    d.line((4, 5, 9, 5), fill=DOOR_LIGHT)
    d.line((4, 5, 4, 14), fill=DOOR_LIGHT)
    d.point((8, 10), fill=KNOB)
    d.rectangle((9, 1, 14, 4), fill=WHITE)                  # bubble
    d.point((9, 1), fill=NIGHT); d.point((14, 4), fill=NIGHT)
    d.point((10, 5), fill=WHITE)
    d.point((11, 2), fill=DOT); d.point((13, 2), fill=DOT)
    return img


def scaled(img, size):
    return img.resize((size, size), Image.NEAREST)


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    small, big = door_16(), door_32()
    frames = {16: small, 32: big, 48: scaled(small, 48), 64: scaled(big, 64),
              128: scaled(big, 128), 256: scaled(big, 256)}
    frames[256].save(ASSETS / "rpgmt.ico", sizes=[(s, s) for s in frames],
                     append_images=[frames[s] for s in (16, 32, 48, 64, 128)])
    frames[256].save(ASSETS / "icon_256.png")
    frames[32].save(ASSETS / "icon_32.png")
    frames[64].save(ASSETS / "favicon.png")
    print("wrote", ASSETS / "rpgmt.ico")


if __name__ == "__main__":
    main()
