from pathlib import Path

from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent
SOURCE_LOGO = BASE_DIR / "app" / "static" / "assets" / "logo.png"
OUTPUT_DIR = BASE_DIR / "app" / "static" / "icons"

REGULAR_SIZES = (192, 512)
APPLE_SIZE = 180
MASKABLE_SIZE = 512
BLUE = (37, 99, 235, 255)
WHITE = (255, 255, 255, 255)
TRANSPARENT = (255, 255, 255, 0)


def _icon(logo: Image.Image, size: int, *, background, padding: float) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), background)
    inner = max(1, int(size * padding))
    resized = logo.copy()
    resized.thumbnail((inner, inner), Image.Resampling.LANCZOS)
    offset = ((size - resized.width) // 2, (size - resized.height) // 2)
    canvas.paste(resized, offset, resized)
    return canvas


def main() -> None:
    if not SOURCE_LOGO.exists():
        raise SystemExit(f"No existe el logo en {SOURCE_LOGO}")

    logo = Image.open(SOURCE_LOGO).convert("RGBA")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for size in REGULAR_SIZES:
        _icon(logo, size, background=TRANSPARENT, padding=1.0).save(
            OUTPUT_DIR / f"icon-{size}x{size}.png"
        )
    _icon(logo, APPLE_SIZE, background=WHITE, padding=0.86).save(
        OUTPUT_DIR / "apple-touch-icon-180x180.png"
    )
    _icon(logo, MASKABLE_SIZE, background=BLUE, padding=0.8).save(
        OUTPUT_DIR / "icon-maskable-512x512.png"
    )
    print(f"Iconos generados en {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
