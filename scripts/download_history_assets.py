# save as: scripts/download_history_assets.py
"""
Скачивает фотографии игроков и иконки трофеев для history_render.
Запустить один раз: python scripts/download_history_assets.py
"""
import os
import sys
from pathlib import Path
from urllib.request import urlretrieve, Request
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PHOTOS_DIR = PROJECT_ROOT / "assets" / "history" / "photos"
TROPHIES_DIR = PROJECT_ROOT / "assets" / "history" / "trophies"

PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
TROPHIES_DIR.mkdir(parents=True, exist_ok=True)

# --- Фотографии игроков ---
PLAYER_PHOTOS = {
    # slug -> URL
    # Примечание: Pinterest-ссылки нельзя скачать напрямую.
    # Скачайте martinez.png вручную с Pinterest и положите в assets/history/photos/
    # "martinez": "https://...",  # скачать вручную
    "sommer": "https://intermilan.bynder.com/transform/0b09313d-0d76-460f-8029-01c676fcd94d/Sommer_2x?quality=100&io=transform:fill,width:2304,height:2766&format=webp",
    "rohl": "https://www.liverpoolworld.uk/jpim-static/image/2025/09/02/6/11/GettyImages-2228106579.jpeg?width=1200&auto=webp&quality=75&crop=3:2,smart&trim=",
}

# --- Трофеи ---
TROPHY_URLS = {
    "ballon_dor": "https://png.pngtree.com/png-clipart/20250621/original/pngtree-3d-ballon-d-or-football-trophy-no-background-png-image_21215466.png",
    "golden_boy": "https://pbs.twimg.com/media/EXbqAzYWsAEthwW.jpg",
    "golden_boot": "https://png.pngtree.com/png-clipart/20250515/original/pngtree-golden-football-boot-trophy-illustration-png-image_20976748.png",
    "golden_glove": "https://images.yampi.me/assets/stores/hypeshoppers/uploads/images/trofeu-luva-de-ouro-premio-melhor-goleiro-futebol-promocao-645af76d7984e-large.png",
}


def download(url: str, dest: Path) -> bool:
    if dest.exists():
        print(f"  [skip] {dest.name} уже есть")
        return True
    print(f"  [download] {url[:80]}...")
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req) as resp:
            data = resp.read()
        dest.write_bytes(data)
        print(f"  [ok] → {dest}")
        return True
    except Exception as e:
        print(f"  [FAIL] {e}")
        return False


def guess_ext(url: str) -> str:
    low = url.lower().split("?")[0]
    if low.endswith(".png"):
        return ".png"
    if low.endswith(".webp") or "format=webp" in url.lower():
        return ".webp"
    if low.endswith((".jpg", ".jpeg")):
        return ".jpg"
    return ".png"


def main():
    print("=== Скачиваю фотографии игроков ===")
    for slug, url in PLAYER_PHOTOS.items():
        ext = guess_ext(url)
        dest = PHOTOS_DIR / f"{slug}{ext}"
        download(url, dest)

    print()
    print("=== Скачиваю трофеи ===")
    for name, url in TROPHY_URLS.items():
        ext = guess_ext(url)
        dest = TROPHIES_DIR / f"{name}{ext}"
        download(url, dest)

    print()
    print("=== ВАЖНО ===")
    martinez_exists = any((PHOTOS_DIR / f"martinez{e}").exists() for e in [".png", ".jpg", ".webp"])
    if not martinez_exists:
        print("⚠  martinez.png — скачайте ВРУЧНУЮ с Pinterest:")
        print("   https://ru.pinterest.com/pin/503840277084591690/")
        print(f"   и положите в: {PHOTOS_DIR}/martinez.png")
    print()
    print("Если фотографии в JPG/WEBP и нужен прозрачный фон,")
    print("удалите фон в Photoshop/remove.bg и сохраните как .png")


if __name__ == "__main__":
    main()
