import os
import json
import html
import re
import time
from datetime import datetime, timezone
import feedparser
import requests

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

SEEN_FILE = "seen_articles.json"

CROSSREF_HEADERS = {
    "User-Agent": "PoliSciRadarBot/1.1 (https://github.com; mailto:polisci-bot@actions.local)"
}
RSS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

# Ключевые слова для отсева обложек, оглавлений и технических страниц
TRASH_KEYWORDS = [
    "front matter", "back matter", "cover and", "cover page",
    "table of contents", "contents", "issue information",
    "editorial board", "corrigendum", "erratum", "errata",
    "author index", "subject index", "book review", "book reviews",
    "volume index", "title page", "preface", "acknowledgement",
    "in memoriam", "obituary"
]

CROSSREF_JOURNALS = [
    # --- Российские издания (ВАК К1 / RSCI / РАН / МГИМО) ---
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
        "name": "International Organization (Cambridge)",
        "issns": ["0020-8183", "1531-5088"]
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
        "name": "Perspectives on Politics",
        "issns": ["1537-5927", "1541-0986"]
    }
]

RSS_FEEDS = [
    {
        "name": "Comparative Political Studies (SAGE RSS)",
        "url": "https://journals.sagepub.com/action/showFeed?ui=0&mi=eh2ecc&ai=2b4&jc=cpsa&type=etoc&feed=rss"
    }
]


def clean_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    clean = re.sub(r"<[^>]+>", " ", raw_html)
    return " ".join(clean.split())


def is_trash_title(title: str) -> bool:
    """Проверяет, не является ли запись обложкой, оглавлением или опечаткой."""
    lowered = title.lower()
    return any(keyword in lowered for keyword in TRASH_KEYWORDS)


def extract_pub_year(item: dict) -> int:
    """Извлекает год публикации из метаданных Crossref."""
    for key in ("published-online", "published-print", "published", "issued", "created"):
        parts = item.get(key, {}).get("date-parts", [])
        if parts and parts[0] and parts[0][0]:
            try:
                return int(parts[0][0])
            except (ValueError, TypeError):
                pass
    return 0


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
            print(f"[WARN] Лимит сообщений Telegram. Ждем {retry_after} сек...")
            time.sleep(retry_after + 1)
            continue
        if res.ok:
            return True
        if "can't parse entities" in res.text and parse_mode:
            print("[WARN] Ошибка разметки, отправляю чистым текстом...")
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
        time.sleep(2.0)
    return success


def fetch_from_crossref(journal_cfg: dict, rows: int = 4) -> list:
    """Получает свежие статьи через Crossref REST API с фильтрацией по дате и контенту."""
    current_year = datetime.now(timezone.utc).year
    # Статьи старше прошлого года игнорируются
    min_year = current_year - 1

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

                # 1. Проверка года публикации
                year = extract_pub_year(item)
                if year and year < min_year:
                    print(f"    [SKIP OLD] Статья {doi} от {year} года (слишком старая)")
                    continue

                # 2. Выбор названия (приоритет кириллице, если есть)
                titles = item.get("title", [])
                chosen_title = titles[0] if titles else "Без названия"
                for t in titles:
                    if re.search(r"[а-яА-ЯёЁ]", t):
                        chosen_title = t
                        break

                # 3. Отсев обложек, оглавлений и служебных страниц
                if is_trash_title(chosen_title):
                    print(f"    [SKIP TRASH] Пропуск тех. страницы: {chosen_title}")
                    continue

                link = item.get("URL") or f"https://doi.org/{doi}"

                # 4. Форматирование авторов
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

                # 5. Аннотация
                raw_abstract = item.get("abstract", "")
                abstract = clean_html(raw_abstract)

                articles.append({
                    "id": f"doi:{doi.lower()}",
                    "title": chosen_title,
                    "link": link,
                    "journal": journal_cfg["name"],
                    "authors": authors_str,
                    "summary": abstract
                })

            if articles:
                break

        except Exception as e:
            print(f"[WARN] Ошибка Crossref для {issn}: {e}")

    return articles


def fetch_from_rss(feed_cfg: dict, rows: int = 3) -> list:
    articles = []
    try:
        r = requests.get(feed_cfg["url"], headers=RSS_HEADERS, timeout=20)
        if r.status_code != 200:
            return articles

        feed = feedparser.parse(r.content)
        for entry in feed.entries[:rows]:
            art_id = entry.get("id") or entry.get("link")
            title = entry.get("title", "Новая публикация")

            if not art_id or is_trash_title(title):
                continue

            articles.append({
                "id": f"rss:{art_id}",
                "title": title,
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
        raise ValueError("TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не заданы!")

    seen = load_seen()
    new_seen = set(seen)
    print(f"[INFO] Сохранено ранее: {len(seen)}")

    is_first_run = len(seen) == 0
    limit = 1 if is_first_run else 2

    # Опрос Crossref
    print(f"\n--- Crossref API ({len(CROSSREF_JOURNALS)} журналов) ---")
    for j_cfg in CROSSREF_JOURNALS:
        print(f"[CHECK] {j_cfg['name']}...")
        articles = fetch_from_crossref(j_cfg, rows=limit)

        for art in articles:
            if art["id"] in seen:
                continue

            print(f"  -> Отправка: {art['title'][:45]}...")
            if post_article(art["title"], art["link"], art["journal"], art["authors"], art["summary"]):
                new_seen.add(art["id"])

    # Опрос RSS
    print(f"\n--- RSS ленты ({len(RSS_FEEDS)}) ---")
    for f_cfg in RSS_FEEDS:
        print(f"[CHECK] {f_cfg['name']}...")
        articles = fetch_from_rss(f_cfg, rows=limit)

        for art in articles:
            if art["id"] in seen:
                continue

            print(f"  -> Отправка: {art['title'][:45]}...")
            if post_article(art["title"], art["link"], art["journal"], art["authors"], art["summary"]):
                new_seen.add(art["id"])

    save_seen(new_seen)
    print(f"\n[INFO] Синхронизация завершена. Всего записей: {len(new_seen)}")


if __name__ == "__main__":
    main()
