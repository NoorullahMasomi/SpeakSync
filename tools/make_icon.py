"""Draw the SpeakSync icon (same design as speaksync/web/icon.svg) -> assets/icon.ico + assets/icon.png"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets"


def draw(size: int = 1024) -> Image.Image:
    s = size / 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    # blue -> violet background
    grad = Image.new("RGBA", (size, size))
    gp = grad.load()
    a, b = (0x4C, 0x8D, 0xFF), (0x9B, 0x7B, 0xFF)
    for y in range(size):
        for x in range(0, size, 1):
            t = (x + y) / (2 * size)
            gp[x, y] = tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)) + (255,)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([2 * s, 2 * s, 62 * s, 62 * s], radius=14 * s, fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    w = (255, 255, 255, 255)
    d.rounded_rectangle([25 * s, 12 * s, 39 * s, 36 * s], radius=7 * s, fill=w)              # microphone
    d.arc([18 * s, 16 * s, 46 * s, 44 * s], start=0, end=180, fill=w, width=int(4 * s))     # holder
    d.line([32 * s, 44 * s, 32 * s, 51 * s], fill=w, width=int(4 * s))
    g = (0x2E, 0xCC, 0x71, 255)                                                               # sound bars
    for x, y, h in ((8, 46, 8), (14, 42, 12), (46, 42, 12), (52, 46, 8)):
        d.rounded_rectangle([x * s, y * s, (x + 4) * s, (y + h) * s], radius=2 * s, fill=g)
    return img


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    big = draw(1024)
    big.resize((512, 512), Image.LANCZOS).save(OUT / "icon.png")
    big.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("icon written to", OUT)
