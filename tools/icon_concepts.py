"""Draws the four icon ideas as 32x32 pixel art and a preview sheet.

Usage: .venv\\Scripts\\python tools\\icon_concepts.py
"""
import pathlib

from PIL import Image, ImageDraw, ImageFont

OUT = pathlib.Path(__file__).resolve().parent.parent / "assets" / "icon_concepts"
S = 32  # pixel-art canvas


def canvas():
    return Image.new("RGBA", (S, S), (0, 0, 0, 0))


def window(d, box, fill_top, fill_bottom, border=(255, 255, 255, 255), shadow=(10, 8, 20, 255)):
    """An RPG Maker style message window: rounded corners, gradient, white frame."""
    x0, y0, x1, y1 = box
    for y in range(y0, y1 + 1):
        t = (y - y0) / max(1, y1 - y0)
        c = tuple(int(a + (b - a) * t) for a, b in zip(fill_top, fill_bottom)) + (255,)
        d.line((x0 + 1, y, x1 - 1, y), fill=c)
    d.rectangle((x0 + 1, y0, x1 - 1, y0), fill=border)
    d.rectangle((x0 + 1, y1, x1 - 1, y1), fill=border)
    d.rectangle((x0, y0 + 1, x0, y1 - 1), fill=border)
    d.rectangle((x1, y0 + 1, x1, y1 - 1), fill=border)
    d.line((x0 + 2, y1 + 1, x1, y1 + 1), fill=shadow)
    d.line((x1 + 1, y0 + 2, x1 + 1, y1), fill=shadow)


def arrow(d, cx, y, color):
    d.line((cx - 2, y, cx + 2, y), fill=color)
    d.line((cx - 1, y + 1, cx + 1, y + 1), fill=color)
    d.point((cx, y + 2), fill=color)


def message_box():
    img = canvas()
    d = ImageDraw.Draw(img)
    window(d, (2, 6, 28, 24), (58, 74, 168), (22, 26, 82))
    for i, x in enumerate((9, 14, 19)):
        d.rectangle((x, 14, x + 2, 16), fill=(255, 255, 255, 255))
    arrow(d, 15, 26, (255, 255, 255, 255))
    d.rectangle((4, 3, 12, 6), fill=(124, 108, 255, 255))  # little name tab
    d.rectangle((4, 3, 12, 3), fill=(255, 255, 255, 255))
    return img


def eye_box():
    img = canvas()
    d = ImageDraw.Draw(img)
    window(d, (2, 6, 28, 24), (36, 18, 48), (12, 6, 18))
    # almond eye
    d.ellipse((7, 11, 23, 19), fill=(240, 236, 230, 255))
    d.ellipse((12, 11, 18, 19), fill=(196, 28, 52, 255))  # red iris
    d.rectangle((14, 13, 16, 17), fill=(20, 4, 10, 255))   # pupil
    d.point((13, 13), fill=(255, 255, 255, 255))           # glint
    d.line((7, 15, 8, 15), fill=(20, 4, 10, 255))
    d.line((22, 15, 23, 15), fill=(20, 4, 10, 255))
    d.line((9, 10, 21, 10), fill=(20, 4, 10, 255))         # upper lid
    arrow(d, 15, 26, (196, 28, 52, 255))
    return img


def dream_door():
    img = canvas()
    d = ImageDraw.Draw(img)
    d.ellipse((1, 1, 31, 31), fill=(26, 14, 40, 255))
    d.rectangle((9, 9, 19, 29), fill=(86, 42, 118, 255))     # door
    d.rectangle((9, 9, 19, 9), fill=(160, 96, 200, 255))
    d.rectangle((9, 9, 9, 29), fill=(160, 96, 200, 255))
    d.rectangle((11, 11, 17, 18), fill=(60, 26, 86, 255))    # panel
    d.rectangle((11, 21, 17, 27), fill=(60, 26, 86, 255))
    d.point((17, 20), fill=(255, 214, 102, 255))             # knob
    d.rectangle((6, 29, 24, 30), fill=(12, 6, 20, 255))      # floor
    # speech bubble
    d.rectangle((19, 3, 29, 9), fill=(255, 255, 255, 255))
    d.point((19, 3), fill=(0, 0, 0, 0)); d.point((29, 3), fill=(0, 0, 0, 0))
    d.point((19, 9), fill=(0, 0, 0, 0)); d.point((29, 9), fill=(0, 0, 0, 0))
    d.line((20, 10, 21, 10), fill=(255, 255, 255, 255)); d.point((20, 11), fill=(255, 255, 255, 255))
    for x in (21, 24, 27):
        d.point((x, 6), fill=(26, 14, 40, 255))
    return img


def sketch_friends():
    img = canvas()
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 31, 31), fill=(250, 250, 246, 255))
    ink = (17, 17, 17, 255)
    for cx, cy, r in ((9, 22, 5), (16, 20, 6), (23, 22, 5)):   # three round heads
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=ink, fill=(255, 255, 255, 255))
        d.point((cx - 2, cy), fill=ink); d.point((cx + 2, cy), fill=ink)
    d.ellipse((11, 13, 21, 18), fill=ink)                    # middle one's dark hair
    d.rectangle((0, 28, 31, 31), fill=(250, 250, 246, 255))
    # "!" bubble
    d.rectangle((12, 2, 20, 10), outline=ink, fill=(255, 255, 255, 255))
    d.point((12, 2), fill=(250, 250, 246, 255)); d.point((20, 2), fill=(250, 250, 246, 255))
    d.point((12, 10), fill=(250, 250, 246, 255)); d.point((20, 10), fill=(250, 250, 246, 255))
    d.line((15, 11, 16, 12), fill=ink)
    d.line((16, 4, 16, 7), fill=ink); d.point((16, 9), fill=ink)
    return img


CONCEPTS = [("1  Message box", message_box), ("2  Eye in the box", eye_box),
            ("3  Dream door", dream_door), ("4  Sketch friends", sketch_friends)]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    tiles = []
    for i, (name, fn) in enumerate(CONCEPTS, 1):
        art = fn()
        art.save(OUT / f"concept{i}_32.png")
        tiles.append((name, art))
    # Preview sheet: each idea big, plus actual taskbar sizes, on dark and light backgrounds.
    cell_w, cell_h = 300, 380
    sheet = Image.new("RGB", (cell_w * len(tiles), cell_h), (20, 18, 31))
    d = ImageDraw.Draw(sheet)
    font = ImageFont.truetype("segoeuib.ttf", 18)
    small = ImageFont.truetype("segoeui.ttf", 12)
    for i, (name, art) in enumerate(tiles):
        x = i * cell_w
        sheet.paste(art.resize((224, 224), Image.NEAREST), (x + 38, 50), art.resize((224, 224), Image.NEAREST))
        d.text((x + cell_w // 2, 18), name, font=font, fill=(241, 238, 252), anchor="mt")
        for j, (size, bg) in enumerate(((16, (20, 18, 31)), (32, (20, 18, 31)), (16, (240, 240, 240)),
                                        (32, (240, 240, 240)))):
            bx = x + 30 + j * 62
            d.rectangle((bx, 300, bx + 52, 352), fill=bg)
            small_art = art.resize((size, size), Image.NEAREST)
            sheet.paste(small_art, (bx + 26 - size // 2, 326 - size // 2), small_art)
        d.text((x + cell_w // 2, 362), "taskbar sizes: 16 / 32 px", font=small, fill=(165, 159, 196), anchor="mt")
    sheet.save(OUT / "preview.png")
    print(OUT / "preview.png")


if __name__ == "__main__":
    main()
