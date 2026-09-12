import os
import json
import html
import re
import feedparser
import requests

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Список RSS-лент журналов по политологии
FEEDS = [
    # American Political Science Review (Cambridge)
    "https://www.cambridge.org/core/rss/product/id/6A72635B891F965FE8A1E7DAECACDB8C",
    # Полис. Политические исследования
    "https://www.politstudies.ru/rss/",
    # Comparative Political Studies (SAGE)
    "https://journals.sagepub.com/action/showFeed?ui=0&mi=eh2ecc&ai=2b4&jc=cpsa&type=etoc&feed=rss",
]

SEEN_FILE = "seen_articles.json"

def clean_html(raw_html: str) -> str:
    clean = re.sub(r"<[^>]+>", "", raw_html)
    return " ".join(clean.split())

def load_seen() -> set:
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_seen(seen_ids: set):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(seen_ids)), f, ensure_ascii=False, indent=2)

def send_post(title: str, link: str, summary: str, source: str):
    text = (
        f"📄 <b>{html.escape(title)}</b>\n\n"
        f"🏛 <i>{html.escape(source)}</i>\n\n"
    )
    if summary:
        # Обрезаем аннотацию, чтобы не перегружать пост
        short_summary = summary[:400].rsplit(" ", 1)[0]
        text += f"{html.escape(short_summary)}...\n\n"
    
    text += f'🔗 <a href="{link}">Читать статью</a>'

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    res = requests.post(url, json=payload, timeout=15)
    res.raise_for_status()

def main():
    seen = load_seen()
    new_seen = set(seen)

    for url in FEEDS:
        try:
            feed = feedparser.parse(url)
            source_name = feed.feed.get("title", "Научный журнал")

            # Проверяем 5 самых свежих публикаций в фиде
            for entry in feed.entries[:5]:
                article_id = entry.get("id") or entry.get("link")
                if not article_id or article_id in seen:
                    continue

                title = entry.get("title", "Без названия")
                link = entry.get("link", "")
                raw_summary = entry.get("summary") or entry.get("description") or ""
                summary = clean_html(raw_summary)

                send_post(title, link, summary, source_name)
                new_seen.add(article_id)

        except Exception as e:
            print(f"Ошибка при обработке {url}: {e}")

    save_seen(new_seen)

if __name__ == "__main__":
    main()
