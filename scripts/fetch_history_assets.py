#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скачивает фото победителей и PNG трофеев в ``assets/history/`` (имена совпадают с slug в data/season_history.json).

Запуск из корня проекта::

    python scripts/fetch_history_assets.py

Для вырезания чёрного фона у JPG/WebP используйте внешний редактор или ``rembg``;
в рендере фото показываются в круглой маске.
"""
from __future__ import annotations

import os
import ssl
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHOTOS = os.path.join(ROOT, "assets", "history", "photos")
TROPHIES = os.path.join(ROOT, "assets", "history", "trophies")

# URL → относительное имя файла в photos/ или trophies/
ASSETS: list[tuple[str, str]] = [
    (
        "https://intermilan.bynder.com/transform/0b09313d-0d76-460f-8029-01c676fcd94d/Sommer_2x?quality=100&io=transform:fill,width:2304,height:2766&format=webp",
        os.path.join("photos", "sommer.webp"),
    ),
    (
        "https://www.liverpoolworld.uk/jpim-static/image/2025/09/02/6/11/GettyImages-2228106579.jpeg?width=1200&auto=webp&quality=75&crop=3:2,smart&trim=",
        os.path.join("photos", "rohl.jpg"),
    ),
    (
        "https://png.pngtree.com/png-clipart/20250621/original/pngtree-3d-ballon-d-or-football-trophy-no-background-png-image_21215466.png",
        os.path.join("trophies", "ballon_dor.png"),
    ),
    (
        "https://png.pngtree.com/png-clipart/20250515/original/pngtree-golden-football-boot-trophy-illustration-png-image_20976748.png",
        os.path.join("trophies", "golden_boot.png"),
    ),
    (
        "https://images.yampi.me/assets/stores/hypeshoppers/uploads/images/trofeu-luva-de-ouro-premio-melhor-goleiro-futebol-promocao-645af76d7984e-large.png",
        os.path.join("trophies", "golden_glove.png"),
    ),
    (
        "https://pbs.twimg.com/media/EXbqAzYWsAEthwW.jpg",
        os.path.join("trophies", "golden_boy.jpg"),
    ),
]


def main() -> None:
    os.makedirs(PHOTOS, exist_ok=True)
    os.makedirs(TROPHIES, exist_ok=True)
    ctx = ssl.create_default_context()
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ctx),
    )
    opener.addheaders = [
        ("User-Agent", "Mozilla/5.0 (compatible; HistoryAssets/1.0)"),
    ]
    urllib.request.install_opener(opener)
    base = os.path.join(ROOT, "assets", "history")
    for url, rel in ASSETS:
        dest = os.path.join(base, rel)
        print(url, "->", dest)
        try:
            urllib.request.urlretrieve(url, dest)
        except Exception as e:
            print("  FAIL:", e)
    print(
        "\nПинтерест для martinez часто требует авторизацию — сохраните фото вручную как",
        os.path.join(PHOTOS, "martinez.png"),
    )


if __name__ == "__main__":
    main()
