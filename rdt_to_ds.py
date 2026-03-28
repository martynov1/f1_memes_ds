"""
Скрипт для забора мемов из r/formuladank и постинга в Discord через webhook.
Запускать раз в день (вручную или через cron/launchd).
Использует RSS-ленту Reddit — никаких API-ключей не нужно.
"""

import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from dotenv import load_dotenv
import requests

load_dotenv()

# ── Настройки ──────────────────────────────────────────────
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
SUBREDDIT = "formuladank"
# Максимум постов за один запуск (чтобы не спамить канал)
MAX_POSTS_PER_RUN = 10
# Файл для хранения уже отправленных постов
POSTED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rdt_to_ds_posted.json")
# ───────────────────────────────────────────────────────────

USER_AGENT = "F1MemesBot/1.0"
ATOM_NS = "{http://www.w3.org/2005/Atom}"
MEDIA_NS = "{http://search.yahoo.com/mrss/}"


def load_posted_ids() -> set:
    if os.path.exists(POSTED_FILE):
        with open(POSTED_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_posted_ids(ids: set):
    trimmed = list(ids)[-500:]
    with open(POSTED_FILE, "w") as f:
        json.dump(trimmed, f)


def fetch_top_memes() -> list[dict]:
    """Забрать топ мемы за день из r/formuladank через RSS. Сначала за day, если новых нет — за week."""
    memes = _fetch_memes_for_period("day")
    return memes


def _fetch_memes_for_period(period: str) -> list[dict]:
    """Забрать топ мемы за указанный период."""
    url = f"https://www.reddit.com/r/{SUBREDDIT}/top.rss?t={period}&limit=20"
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()

    root = ET.fromstring(resp.text)
    memes = []

    for entry in root.findall(f"{ATOM_NS}entry"):
        post_id = entry.find(f"{ATOM_NS}id").text or ""
        title = entry.find(f"{ATOM_NS}title").text or ""
        link = entry.find(f"{ATOM_NS}link").attrib.get("href", "")

        # Ищем картинку в media:thumbnail
        thumb = entry.find(f"{MEDIA_NS}thumbnail")
        # Также ищем в media:content
        media_content = entry.find(f"{MEDIA_NS}content")

        image_url = None
        if thumb is not None:
            image_url = thumb.attrib.get("url", "")
        if media_content is not None:
            media_url = media_content.attrib.get("url", "")
            if media_url:
                image_url = media_url

        # Ещё пробуем вытащить картинку из HTML в <content>
        if not image_url:
            content_el = entry.find(f"{ATOM_NS}content")
            if content_el is not None and content_el.text:
                img_match = re.search(r'<img\s+src="([^"]+)"', content_el.text)
                if img_match:
                    image_url = img_match.group(1).replace("&amp;", "&")

        if not image_url:
            continue

        # Reddit превью — заменяем на полный размер если это i.redd.it
        image_url = image_url.replace("&amp;", "&")
        # preview.redd.it -> i.redd.it (полный размер)
        if "preview.redd.it" in image_url:
            # Попробуем вытащить оригинальный URL из content
            content_el = entry.find(f"{ATOM_NS}content")
            if content_el is not None and content_el.text:
                # Ищем ссылку на i.redd.it
                orig_match = re.search(r'href="(https://i\.redd\.it/[^"]+)"', content_el.text)
                if orig_match:
                    image_url = orig_match.group(1)

        memes.append({
            "id": post_id,
            "title": title,
            "url": image_url,
            "permalink": link,
        })

    return memes


def post_to_discord(meme: dict):
    payload = {
        "embeds": [{
            "title": meme["title"],
            "url": meme["permalink"],
            "image": {"url": meme["url"]},
            "footer": {"text": f"r/{SUBREDDIT}"},
            "color": 0xFF1801,
        }]
    }
    resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
    resp.raise_for_status()


def main():
    if not DISCORD_WEBHOOK_URL:
        print("Ошибка: задай DISCORD_WEBHOOK_URL")
        sys.exit(1)

    print(f"Забираю топ мемы из r/{SUBREDDIT}...")
    posted_ids = load_posted_ids()

    # Сначала берём за день
    memes = _fetch_memes_for_period("day")
    new_memes = [m for m in memes if m["id"] not in posted_ids]
    print(f"  Найдено за день: {len(memes)}, новых: {len(new_memes)}")

    # Если новых за день нет — берём за неделю
    if not new_memes:
        print("  Новых за день нет, смотрю за неделю...")
        memes = _fetch_memes_for_period("week")
        new_memes = [m for m in memes if m["id"] not in posted_ids]
        print(f"  Найдено за неделю: {len(memes)}, новых: {len(new_memes)}")

    # Постим от старых к новым
    new_memes.reverse()

    sent = 0
    for meme in new_memes[:MAX_POSTS_PER_RUN]:
        try:
            post_to_discord(meme)
            posted_ids.add(meme["id"])
            sent += 1
            print(f"  ✓ {meme['title'][:60]}")
            time.sleep(2)
        except requests.RequestException as e:
            print(f"  ✗ Ошибка при отправке: {e}")

    save_posted_ids(posted_ids)
    print(f"Готово! Отправлено {sent} мемов в Discord.")


if __name__ == "__main__":
    main()
