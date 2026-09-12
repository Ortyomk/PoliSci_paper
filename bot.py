import os
import json
import html
import re
import feedparser
import requests

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

FEEDS = [
    # Cambridge: American Political Science Review
    "https://www.cambridge.org/core/rss/product/id/6A72635B891F965FE8A1E7DAECACDB8C",
    # Полис. Политические исследования
    "https://www.politstudies.ru/rss/",
    # SAGE: Comparative Political Studies
    "https://journals.sagepub.com/action/showFeed?ui=0&mi=eh2ecc&ai=2b4&jc=cpsa&type=etoc&feed=rss",
]

SEEN_FILE = "seen_articles.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

def clean_html(raw_html: str) -> str:
    clean = re.sub(r"<[^>]+>", " ", raw_html)
    return " ".join(clean.split())

def load_seen() -> set:
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data) if isinstance(data, list) else set()
        except Exception as e:
            print(f"[WARN] Ошибка чтения seen_articles.json: {e}")
            return set()
    return set()

def save_seen(seen_ids: set):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(seen_ids)), f, ensure_ascii=False, indent=2)

def send_post(title: str, link: str, summary: str, source: str):
    clean_title = html.escape(title.strip())
    clean_source = html.escape(source.strip())
    
    html_text = (
        f"📄 <b>{clean_title}</b>\n\n"
        f"🏛 <i>{clean_source}</i>\n\n"
    )
    if summary:
        short_summary = html.escape(summary[:300].rsplit(" ", 1)[0])
        html_text += f"{short_summary}...\n\n"
    
    if link:
        html_text += f'🔗 <a href="{link.strip()}">Читать статью</a>'

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": html_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }

    res = requests.post(url, json=payload, timeout=20)
    
    # Если ошибка 400 вызвана HTML-разметкой, отправляем чистым текстом
    if not res.ok:
        print(f"[WARN] Telegram вернул {res.status_code}: {res.text}. Пробую чистый текст...")
        plain_text = f"📄 {title.strip()}\n\n🏛 {source.strip()}\n\n"
        if summary:
            plain_text += f"{summary[:300].rsplit(' ', 1)[0]}...\n\n"
        if link:
            plain_text += f"🔗 Ссылка: {link.strip()}"
        
        res = requests.post(url, json={"chat_id": CHAT_ID, "text": plain_text}, timeout=20)

    if not res.ok:
        print(f"[FATAL ERROR] Ответ Telegram API: {res.text}")
    
    res.raise_for_status()

def main():
    seen = load_seen()
    new_seen = set(seen)
    print(f"[INFO] В базе сохранено публикаций: {len(seen)}")

    for url in FEEDS:
        print(f"\n[INFO] Проверяю: {url}")
        try:
            resp = requests.get(url, headers=HEADERS, timeout=25)
            if resp.status_code != 200:
                print(f"[WARN] HTTP {resp.status_code}, пропускаю.")
                continue

            feed = feedparser.parse(resp.content)
            source_name = feed.feed.get("title", "Научный журнал")
            entries = feed.entries[:3]
            print(f"[INFO] Найдено записей: {len(entries)}")

            for entry in entries:
                article_id = entry.get("id") or entry.get("link")
                if not article_id or article_id in seen:
                    continue

                title = entry.get("title", "Новая публикация")
                link = entry.get("link", "")
                summary = clean_html(entry.get("summary") or entry.get("description") or "")

                print(f"[POST] Отправка: {title[:40]}...")
                send_post(title, link, summary, source_name)
                new_seen.add(article_id)

        except Exception as e:
            print(f"[ERROR] Ошибка ленты {url}: {e}")

    save_seen(new_seen)

if __name__ == "__main__":
    main()
