import os
import json
import html
import re
import time
import feedparser
import requests

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

SEEN_FILE = "seen_articles.json"

# Вежливый User-Agent для Crossref (помещает запросы в приоритетный пул API)
CROSSREF_HEADERS = {
    "User-Agent": "PoliSciRadarBot/1.0 (https://github.com; mailto:polisci-bot@actions.local)"
}
RSS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

# --------------------------------------------------------------------------
# СПИСОК ЖУРНАЛОВ ДЛЯ МОНИТОРИНГА ЧЕРЕЗ CROSSREF (ПО ISSN)
# --------------------------------------------------------------------------
CROSSREF_JOURNALS = [
    # --- Российские издания (ВАК К1 / RSCI / РАН) ---
    {
        "name": "Полис. Политические исследования",
        "issns": ["1026-9487", "2071-8713"]
    },
    {
        "name": "Современная Европа (ИЕ РАН)",
        "issns": ["0201-7083", "2658-4824"]
    },
    {
        "name": "Политическая наука (ИНИОН РАН)",
        "issns": ["1998-1775"]
    },
    {
        "name": "Сравнительная политика (Comparative Politics Russia)",
        "issns": ["2221-3279", "2412-4990"]
    },
    {
        "name": "Вестник МГИМО-Университета",
        "issns": ["2071-8160", "2541-9099"]
    },
    {
        "name": "Россия в глобальной политике",
        "issns": ["1810-6439", "2618-8597"]
    },
    {
        "name": "Мировая экономика и международные отношения (МЭиМО)",
        "issns": ["0202-7496", "2686-7494"]
    },
    {
        "name": "Вестник Пермского университета. Политология",
        "issns": ["2218-1067", "2412-7043"]
    },

    # --- Ведущие международные издания ---
    {
        "name": "American Political Science Review (APSR)",
        "issns": ["0003-0554", "1537-5943"]
    },
    {
        "name": "Comparative Political Studies (CPS)",
        "issns": ["0010-4140", "1552-3829"]
    },
    {
        "name": "West European Politics",
        "issns": ["0140-2382", "1743-9655"]
    },
    {
        "name": "European Journal of Political Research (EJPR)",
        "issns": ["0304-4130", "1475-6765"]
    },
    {
        "name": "British Journal of Political Science (BJPS)",
        "issns": ["0007-1234", "1469-2112"]
    },
    {
        "name": "Party Politics",
        "issns": ["1354-0688", "1460-3667"]
    },
    {
        "name": "Electoral Studies",
        "issns": ["0261-3794"]
    },
    {
        "name": "Democratization",
        "issns": ["1351-0347", "1743-890X"]
    },
    {
        "name": "Journal of European Public Policy (JEPP)",
        "issns": ["1350-1763", "1466-4429"]
    },
    {
        "name": "International Affairs (Chatham House)",
        "issns": ["0020-5850", "1468-2346"]
    },
    {
        "name": "Perspectives on Politics",
        "issns": ["1537-5927", "1541-0986"]
    }
]

# Прямые RSS-ленты (для источников, где RSS стабильно отдаётся без блокировок)
RSS_FEEDS = [
    {
        "name": "Comparative Political Studies (SAGE RSS)",
        "url": "https://journals.sagepub.com/action/showFeed?ui=0&mi=eh2ecc&ai=2b4&jc=cpsa&type=etoc&feed=rss"
    }
]


def clean_html(raw_html: str) -> str:
    """Удаляет теги XML/HTML и нормализует пробелы."""
    if not raw_html:
        return ""
    clean = re.sub(r"<[^>]+>", " ", raw_html)
    return " ".join(clean.split())


def load_seen() -> set:
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data) if isinstance(data, list) else set()
        except Exception as e:
            print(f"[WARN] Ошибка чтения {SEEN_FILE}: {e}")
            return set()
    return set()


def save_seen(seen_ids: set):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(seen_ids)), f, ensure_ascii=False, indent=2)


def send_telegram_message(text: str, parse_mode: str = "HTML") -> bool:
    """Отправляет сообщение в Telegram с защитой от лимитов (Error 429)."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "disable_web_page_preview": False
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    for attempt in range(3):
        res = requests.post(url, json=payload, timeout=20)
        if res.status_code == 429:
            retry_after = res.json().get("parameters", {}).get("retry_after", 10)
            print(f"[WARN] Превышен лимит сообщений Telegram. Ожидание {retry_after} сек...")
            time.sleep(retry_after + 1)
            continue
        if res.ok:
            return True
        if "can't parse entities" in res.text and parse_mode:
            # Сбой разметки — пробуем отправить чистым текстом
            print("[WARN] Сбой HTML-парсинга, переотправка чистым текстом...")
            return send_telegram_message(clean_html(text), parse_mode="")
        print(f"[ERROR] Ошибка Telegram ({res.status_code}): {res.text}")
        break

    return False


def post_article(title: str, link: str, journal: str, authors: str = "", summary: str = ""):
    clean_title = html.escape(title.strip())
    clean_journal = html.escape(journal.strip())

    msg = f"📄 <b>{clean_title}</b>\n\n"
    msg += f"🏛 <i>{clean_journal}</i>\n"

    if authors:
        msg += f"✍️ <i>{html.escape(authors.strip())}</i>\n"

    msg += "\n"

    if summary:
        short = summary[:320].rsplit(" ", 1)[0]
        msg += f"{html.escape(short)}...\n\n"

    if link:
        msg += f'🔗 <a href="{link.strip()}">Читать публикацию</a>'

    success = send_telegram_message(msg, parse_mode="HTML")
    if success:
        # Пауза в 2 секунды между постами, чтобы не перегружать канал
        time.sleep(2.0)
    return success


def fetch_from_crossref(journal_cfg: dict, rows: int = 2) -> list:
    """Получает последние опубликованные статьи журнала через Crossref REST API."""
    articles = []
    for issn in journal_cfg["issns"]:
        url = "https://api.crossref.org/works"
        params = {
            "filter": f"issn:{issn},type:journal-article",
            "sort": "published",
            "order": "desc",
            "rows": rows
        }
        try:
            r = requests.get(url, params=params, headers=CROSSREF_HEADERS, timeout=20)
            if r.status_code != 200:
                continue

            items = r.json().get("message", {}).get("items", [])
            if not items:
                continue

            for item in items:
                doi = item.get("DOI")
                if not doi:
                    continue

                titles = item.get("title", [])
                title = titles[0] if titles else "Без названия"
                link = item.get("URL") or f"https://doi.org/{doi}"

                # Форматирование списка авторов: И. Иванов, П. Петров
                raw_authors = item.get("author", [])
                authors_list = []
                for a in raw_authors[:4]:
                    given = a.get("given", "").strip()
                    family = a.get("family", "").strip()
                    if family and given:
                        authors_list.append(f"{given[0]}. {family}")
                    elif family:
                        authors_list.append(family)
                if len(raw_authors) > 4:
                    authors_str = ", ".join(authors_list) + " et al."
                else:
                    authors_str = ", ".join(authors_list)

                # Обработка аннотации
                raw_abstract = item.get("abstract", "")
                abstract = clean_html(raw_abstract)

                articles.append({
                    "id": f"doi:{doi.lower()}",
                    "title": title,
                    "link": link,
                    "journal": journal_cfg["name"],
                    "authors": authors_str,
                    "summary": abstract
                })
            
            # Если по первому ISSN данные успешно найдены — прерываем перебор
            if articles:
                break

        except Exception as e:
            print(f"[WARN] Сбой при запросе к Crossref для {issn}: {e}")

    return articles


def fetch_from_rss(feed_cfg: dict, rows: int = 2) -> list:
    """Получает публикации из прямого RSS-фида."""
    articles = []
    try:
        r = requests.get(feed_cfg["url"], headers=RSS_HEADERS, timeout=20)
        if r.status_code != 200:
            return articles

        feed = feedparser.parse(r.content)
        for entry in feed.entries[:rows]:
            art_id = entry.get("id") or entry.get("link")
            if not art_id:
                continue

            articles.append({
                "id": f"rss:{art_id}",
                "title": entry.get("title", "Новая публикация"),
                "link": entry.get("link", ""),
                "journal": feed_cfg["name"],
                "authors": "",
                "summary": clean_html(entry.get("summary") or entry.get("description") or "")
            })
    except Exception as e:
        print(f"[WARN] Ошибка RSS {feed_cfg['name']}: {e}")

    return articles


def main():
    if not BOT_TOKEN or not CHAT_ID:
        raise ValueError("Токен бота или ID канала не найдены в переменных окружения!")

    seen = load_seen()
    new_seen = set(seen)
    print(f"[INFO] База уже опубликованных записей: {len(seen)}")

    # При первом запуске берем по 1 статье с журнала, чтобы не спамить в канал
    is_first_run = len(seen) == 0
    limit_per_journal = 1 if is_first_run else 2

    # 1. Опрос журналов через Crossref API
    print(f"\n--- Опрос Crossref API ({len(CROSSREF_JOURNALS)} журналов) ---")
    for j_cfg in CROSSREF_JOURNALS:
        print(f"[CHECK] {j_cfg['name']}...")
        articles = fetch_from_crossref(j_cfg, rows=limit_per_journal)

        for art in articles:
            if art["id"] in seen:
                continue

            print(f"  -> Отправляю: {art['title'][:45]}...")
            if post_article(art["title"], art["link"], art["journal"], art["authors"], art["summary"]):
                new_seen.add(art["id"])

    # 2. Опрос рабочих RSS-лент
    print(f"\n--- Опрос RSS-потоков ({len(RSS_FEEDS)} лент) ---")
    for f_cfg in RSS_FEEDS:
        print(f"[CHECK] {f_cfg['name']}...")
        articles = fetch_from_rss(f_cfg, rows=limit_per_journal)

        for art in articles:
            if art["id"] in seen:
                continue

            print(f"  -> Отправляю: {art['title'][:45]}...")
            if post_article(art["title"], art["link"], art["journal"], art["authors"], art["summary"]):
                new_seen.add(art["id"])

    save_seen(new_seen)
    print(f"\n[INFO] Синхронизация завершена. Всего в базе: {len(new_seen)}")


if __name__ == "__main__":
    main()
