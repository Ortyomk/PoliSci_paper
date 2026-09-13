import os
import json
import html
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
import requests

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

SEEN_FILE = "seen_issues.json"

CROSSREF_HEADERS = {
    "User-Agent": "PoliSciIssueRadar/2.0 (mailto:polisci-bot@actions.local)"
}

TRASH_KEYWORDS = [
    "front matter", "back matter", "cover and", "cover page",
    "table of contents", "contents", "issue information",
    "editorial board", "corrigendum", "erratum", "errata",
    "author index", "subject index", "book review", "book reviews",
    "volume index", "title page", "preface", "acknowledgement",
    "in memoriam", "obituary"
]

# Только безопасные издания без юридических рисков
CROSSREF_JOURNALS = [
    # --- Ведущие российские издания (ВАК К1 / RSCI / РАН / МГИМО) ---
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

    # --- Мировые политологические издания ---
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


def clean_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    clean = re.sub(r"<[^>]+>", " ", raw_html)
    return " ".join(clean.split())


def is_trash_title(title: str) -> bool:
    lowered = title.lower()
    return any(keyword in lowered for keyword in TRASH_KEYWORDS)


def extract_pub_year(item: dict) -> int:
    for key in ("published-print", "published-online", "published", "issued", "created"):
        parts = item.get(key, {}).get("date-parts", [])
        if parts and parts[0] and parts[0][0]:
            try:
                return int(parts[0][0])
            except (ValueError, TypeError):
                pass
    return datetime.now(timezone.utc).year


def load_seen() -> set:
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data) if isinstance(data, list) else set()
        except Exception:
            return set()
    return set()


def save_seen(seen_ids: set):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(seen_ids)), f, ensure_ascii=False, indent=2)


def send_telegram_message(text: str) -> bool:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    for attempt in range(3):
        res = requests.post(url, json=payload, timeout=25)
        if res.status_code == 429:
            retry_after = res.json().get("parameters", {}).get("retry_after", 10)
            time.sleep(retry_after + 1)
            continue
        if res.ok:
            return True
        if "can't parse entities" in res.text:
            payload["text"] = clean_html(text)
            payload.pop("parse_mode", None)
            res = requests.post(url, json=payload, timeout=25)
            return res.ok
        print(f"[ERROR] Ошибка Telegram API: {res.text}")
        break
    return False


def post_issue_digest(journal_name: str, issue_label: str, year: int, articles: list) -> bool:
    header = (
        f"📚 <b>Новый выпуск: {html.escape(journal_name)}</b>\n"
        f"🗓 <i>{year} г. • {html.escape(issue_label)}</i>\n\n"
        f"<b>Содержание номера:</b>\n\n"
    )

    items_text = []
    for idx, art in enumerate(articles, start=1):
        clean_title = html.escape(art["title"])
        authors_part = f"\n   ✍️ <i>{html.escape(art['authors'])}</i>" if art["authors"] else ""
        link_part = f'\n   🔗 <a href="{art["link"]}">Читать статью</a>'
        items_text.append(f"<b>{idx}. {clean_title}</b>{authors_part}{link_part}\n\n")

    current_post = header
    posts_to_send = []

    for item in items_text:
        if len(current_post) + len(item) > 3900:
            posts_to_send.append(current_post)
            current_post = header + "<i>(продолжение)</i>\n\n" + item
        else:
            current_post += item

    if current_post:
        posts_to_send.append(current_post)

    success = True
    for part in posts_to_send:
        if not send_telegram_message(part):
            success = False
        time.sleep(2.5)

    return success


def fetch_issues_from_crossref(journal_cfg: dict) -> dict:
    current_year = datetime.now(timezone.utc).year
    min_year = current_year - 1

    grouped = defaultdict(list)

    for issn in journal_cfg["issns"]:
        url = "https://api.crossref.org/works"
        params = {
            "filter": f"issn:{issn},type:journal-article",
            "sort": "published",
            "order": "desc",
            "rows": 35
        }
        try:
            r = requests.get(url, params=params, headers=CROSSREF_HEADERS, timeout=25)
            if r.status_code != 200:
                continue

            items = r.json().get("message", {}).get("items", [])
            for item in items:
                doi = item.get("DOI")
                if not doi:
                    continue

                year = extract_pub_year(item)
                if year < min_year:
                    continue

                volume = str(item.get("volume", "")).strip()
                issue = str(item.get("issue", "")).strip()

                if not issue:
                    continue

                titles = item.get("title", [])
                chosen_title = titles[0] if titles else "Без названия"
                for t in titles:
                    if re.search(r"[а-яА-ЯёЁ]", t):
                        chosen_title = t
                        break

                if is_trash_title(chosen_title):
                    continue

                link = item.get("URL") or f"https://doi.org/{doi}"

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

                article_data = {
                    "title": chosen_title,
                    "link": link,
                    "authors": authors_str
                }

                issue_key = (volume, issue, year)
                grouped[issue_key].append(article_data)

            if grouped:
                break

        except Exception as e:
            print(f"[WARN] Ошибка Crossref для {issn}: {e}")

    return grouped


def main():
    if not BOT_TOKEN or not CHAT_ID:
        raise ValueError("TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не заданы!")

    seen = load_seen()
    new_seen = set(seen)
    
    # ЕСЛИ БАЗА ПУСТАЯ — ВКЛЮЧАЕТСЯ РЕЖИМ ТИХОЙ ИНИЦИАЛИЗАЦИИ
    is_first_run = (len(seen) == 0)

    if is_first_run:
        print("[INFO] База пуста. Режим ТИХОЙ ИНИЦИАЛИЗАЦИИ активирован.")
        print("[INFO] Все текущие номера будут сохранены в базу БЕЗ публикации в Telegram.\n")
    else:
        print(f"[INFO] База загружена. Ранее сохранено номеров: {len(seen)}\n")

    for j_cfg in CROSSREF_JOURNALS:
        journal_name = j_cfg["name"]
        print(f"[CHECK] {journal_name}...")

        issues = fetch_issues_from_crossref(j_cfg)
        if not issues:
            continue

        sorted_keys = sorted(issues.keys(), key=lambda k: (k[2], k[0], k[1]), reverse=True)

        for vol, iss, yr in sorted_keys:
            articles = issues[(vol, iss, yr)]
            if len(articles) < 2:
                continue

            unique_issue_id = f"{journal_name}|vol:{vol}|iss:{iss}|yr:{yr}"

            issue_label = f"Выпуск № {iss}"
            if vol:
                issue_label = f"Том {vol}, {issue_label}"

            # В режиме тихой инициализации просто запоминаем существующие номера
            if is_first_run:
                print(f"  [INIT SILENT] Запомнен: {journal_name} — {issue_label} ({len(articles)} ст.)")
                new_seen.add(unique_issue_id)
                continue

            # В обычном режиме: если номера нет в базе — публикуем
            if unique_issue_id in seen:
                continue

            print(f"  [POST ISSUE] Публикую: {journal_name} — {issue_label} ({len(articles)} ст.)")
            if post_issue_digest(journal_name, issue_label, yr, articles):
                new_seen.add(unique_issue_id)

    save_seen(new_seen)

    if is_first_run:
        print(f"\n[INFO] Инициализация завершена! В базу записано {len(new_seen)} существующих номеров.")
        print("[INFO] В канал ничего не отправлено. Со следующего запуска бот начнет присылать только НОВЫЕ выпуски.")
    else:
        print(f"\n[INFO] Синхронизация завершена. Всего в базе: {len(new_seen)}")


if __name__ == "__main__":
    main()
