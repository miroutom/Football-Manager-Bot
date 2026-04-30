# save as: scripts/remove_bg_history.py
"""
Удаляет фон с фотографий игроков (JPG/WEBP → PNG с прозрачностью).
Требует: pip install rembg pillow onnxruntime
"""
from pathlib import Path

try:
    from rembg import remove
except ImportError:
    print("pip install rembg onnxruntime")
    raise

from PIL import Image

PHOTOS_DIR = Path(__file__).resolve().parent.parent / "assets" / "history" / "photos"
TROPHIES_DIR = Path(__file__).resolve().parent.parent / "assets" / "history" / "trophies"


def process_dir(d: Path):
    for f in d.iterdir():
        if f.suffix.lower() in (".jpg", ".jpeg", ".webp"):
            out = f.with_suffix(".png")
            if out.exists():
                print(f"  [skip] {out.name} уже есть")
                continue
            print(f"  [rembg] {f.name} → {out.name}")
            inp = Image.open(f).convert("RGBA")
            result = remove(inp)
            result.save(out, "PNG")
            print(f"  [ok] {out}")


def main():
    print("=== Удаляю фон с фото игроков ===")
    process_dir(PHOTOS_DIR)
    print()
    print("=== Удаляю фон с трофеев (если JPG) ===")
    process_dir(TROPHIES_DIR)


if __name__ == "__main__":
    main()
