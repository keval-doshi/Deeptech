"""Download freely-licensed demo photos from Wikimedia Commons.

    python tools/fetch_images.py [--per-category 10] [--only spacetech,ai]

Saves 1200x750 JPEGs to static/images/photos/<category>/NN.jpg and records
title, author, license and source for each file in static/images/photos/CREDITS.json.
These are DEMO images for sample data only. Replace them with each startup's
own uploads before launch.
"""
import argparse
import io
import json
import os
import re
import time

import requests
from PIL import Image, ImageOps

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "images", "photos"))
API = "https://commons.wikimedia.org/w/api.php"
HEADERS = {"User-Agent": "DeeptechIndiaDemo/1.0 (https://deeptechindia.in; demo-images@deeptechindia.in) python-requests"}
ALLOWED_LICENSES = re.compile(r"^(cc0|cc[- ]by(-sa)?([- ][0-9.]+)?|public domain|pd\b.*)", re.I)
BLOCKED_WORDS = re.compile(r"logo|map|diagram|chart|graph|poster|stamp|flag|coat of arms|svg|screenshot|scheme|plot", re.I)

QUERIES = {
    "spacetech": ["rocket launch India", "PSLV launch", "satellite in orbit", "rocket engine test", "spacecraft cleanroom"],
    "robotics": ["industrial robot arm factory", "robotic arm", "humanoid robot", "warehouse robot"],
    "ai": ["data center servers", "server room", "computer vision camera", "GPU cluster"],
    "biotech": ["biotechnology laboratory", "laboratory pipette", "cell culture laboratory", "DNA sequencer"],
    "semiconductors": ["silicon wafer", "semiconductor cleanroom", "microchip macro", "printed circuit board"],
    "climatetech": ["carbon capture plant", "forest aerial", "climate monitoring station", "mangrove forest"],
    "clean-energy": ["wind farm", "solar power plant India", "solar panels", "battery energy storage"],
    "agritech": ["rice paddy field India", "farmer field India", "greenhouse farming", "tractor field India"],
    "quantum": ["quantum computer", "dilution refrigerator", "laser optics laboratory", "optical table laser"],
    "medtech": ["ultrasound machine", "patient monitor hospital", "hospital operating room", "medical laboratory equipment", "MRI scanner"],
    "defence": ["radar antenna", "air force aircraft India", "military radar", "fighter jet"],
    "ev-mobility": ["electric scooter", "electric vehicle charging", "lithium ion battery cells", "electric car"],
    "advanced-materials": ["carbon fiber", "materials science laboratory", "graphene", "metal 3D printing"],
    "iot": ["cable-stayed bridge", "smart electricity meter", "wireless sensor module", "metro railway India", "microcontroller board"],
    "drones": ["agricultural drone", "quadcopter drone flying", "drone aerial", "multirotor drone"],
}


def search(query, limit=25):
    params = {
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6, "gsrlimit": limit,
        "gsrsearch": f"{query} filetype:bitmap", "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1400,
    }
    data = {}
    for attempt in range(5):
        response = requests.get(API, params=params, headers=HEADERS, timeout=30)
        if response.ok and response.headers.get("content-type", "").startswith("application/json"):
            data = response.json()
            break
        time.sleep(3 * (attempt + 1))
    time.sleep(0.5)
    pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        license_name = re.sub("<[^>]+>", "", meta.get("LicenseShortName", {}).get("value", "")).strip()
        yield {
            "title": page["title"],
            "width": info.get("width", 0),
            "height": info.get("height", 1),
            "mime": info.get("mime", ""),
            "thumb": info.get("thumburl"),
            "source": info.get("descriptionurl"),
            "license": license_name,
            "author": re.sub("<[^>]+>", "", meta.get("Artist", {}).get("value", "")).strip()[:120],
        }


def acceptable(item):
    ratio = item["width"] / max(item["height"], 1)
    return (item["mime"] == "image/jpeg" and item["width"] >= 1000 and 1.2 <= ratio <= 2.4
            and item["thumb"] and ALLOWED_LICENSES.match(item["license"] or "")
            and not BLOCKED_WORDS.search(item["title"]))


def save(item, path):
    raw = requests.get(item["thumb"], headers=HEADERS, timeout=60).content
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    image = ImageOps.fit(image, (1200, 750), Image.LANCZOS)
    image.save(path, "JPEG", quality=80, optimize=True, progressive=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-category", type=int, default=10)
    parser.add_argument("--only", default="")
    args = parser.parse_args()
    only = {s for s in args.only.split(",") if s}
    os.makedirs(ROOT, exist_ok=True)
    credits_path = os.path.join(ROOT, "CREDITS.json")
    credits = json.load(open(credits_path, encoding="utf-8")) if os.path.exists(credits_path) else {}
    blocked = set(json.load(open(os.path.join(ROOT, "blocklist.json")))) if os.path.exists(
        os.path.join(ROOT, "blocklist.json")) else set()

    for slug, queries in QUERIES.items():
        if only and slug not in only:
            continue
        folder = os.path.join(ROOT, slug)
        os.makedirs(folder, exist_ok=True)
        for f in os.listdir(folder):
            os.remove(os.path.join(folder, f))
        chosen, seen = [], set(blocked)
        rounds = [list(search(q)) for q in queries]
        # Round-robin across queries for variety.
        while len(chosen) < args.per_category and any(rounds):
            for results in rounds:
                while results:
                    item = results.pop(0)
                    if item["title"] not in seen and acceptable(item):
                        seen.add(item["title"])
                        chosen.append(item)
                        break
                if len(chosen) >= args.per_category:
                    break
        for n, item in enumerate(chosen, start=1):
            name = f"{n:02d}.jpg"
            try:
                save(item, os.path.join(folder, name))
            except Exception as exc:  # noqa: BLE001 (best effort)
                print("  skip", item["title"], exc)
                continue
            credits[f"{slug}/{name}"] = {k: item[k] for k in ("title", "author", "license", "source")}
            time.sleep(0.2)
        print(f"{slug}: {len(chosen)} images")
    json.dump(credits, open(credits_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
