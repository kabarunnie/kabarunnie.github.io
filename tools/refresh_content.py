#!/usr/bin/env python3
"""Kabar Unnie content helper (runs locally and in GitHub Actions).

Commands:
  validate   Check app/data/content.json against the schema.
  headlines  Fetch public RSS headlines and write tools/drafts/headlines-*.md.
  refresh    CI job: fetch RSS into data/inbox.json (raw, never shown in the
             app), promote editor-approved items from data/approved/*.json
             into app/data/content.json, then validate.
  post       Post news items not yet in data/posted.json to the Telegram
             channel via the Bot API. Text + links only; the official video
             appears through Telegram's own link preview (nothing re-hosted).
             Skips cleanly when TELEGRAM_BOT_TOKEN / TELEGRAM_CHANNEL_ID are
             missing.
  seed       Mark every current news item as already posted.

Raw RSS headlines are never written into content.json automatically: a
person rewrites them in Bahasa Indonesia, adds the source link and the
Sumber resmi / Belum dikonfirmasi label, and saves them in data/approved/.
Use --dry-run with refresh or post to change nothing.
"""

from __future__ import annotations

import argparse
import os
import time
import urllib.error
import urllib.parse
import json
import ssl
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "app" / "data" / "content.json"
DRAFT_DIR = ROOT / "tools" / "drafts"
DATA_DIR = ROOT / "data"
INBOX = DATA_DIR / "inbox.json"
APPROVED_DIR = DATA_DIR / "approved"
POSTED = DATA_DIR / "posted.json"
MAX_NEWS = 12
WIB = timezone(timedelta(hours=7))
HARI = ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu")
BULAN = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")
HERALD_RSS = "https://www.koreaherald.com/rss/kh_Kpop"

KEYWORDS = (
    "ive", "aespa", "twice", "nayeon", "jeongyeon", "momo", "sana", "jihyo",
    "mina", "dahyun", "chaeyoung", "tzuyu", "le sserafim", "lesserafim",
    "illit", "itzy", "nmixx", "red velvet", "wendy", "irene", "seulgi",
    "joy", "yeri", "blackpink", "jennie", "lisa", "jisoo", "rosé", "rose",
    "babymonster", "kiss of life", "i-dle", "gidle", "(g)i-dle", "idle",
    "hearts2hearts", "rescene", "fifty fifty", "stayc", "meovv", "katseye",
    "girls' generation", "snsd", "taeyeon", "h1-key", "apink", "fromis",
    "wjsn", "mamamoo", "hwasa", "solar", "moonbyul", "wheein", "izna",
    "triples", "kiiikiii", "kiiiikiii", "girl group", "girl-group",
)

NEWS_FIELDS = (
    "id", "badge", "badgeLabel", "group", "color", "initial",
    "title", "hook", "body", "sourceName", "sourceUrl", "time", "publishedAt",
)
SCHED_FIELDS = (
    "id", "date", "when", "group", "color", "initial",
    "title", "meta", "note", "sourceName", "sourceUrl",
)


# Anonymity guard (lower-case fragments that must never appear in published data).
BANNED = tuple(w for w in os.environ.get("KU_BANNED_WORDS", "").lower().split(",") if w.strip())


def load_content(path: Path = CONTENT) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def validate(path: Path = CONTENT) -> int:
    data = load_content(path)
    errors: list[str] = []

    for key in ("brand", "handle", "channelUrl", "disclaimer", "updatedAt", "news", "schedule", "quiz", "vote"):
        if key not in data:
            errors.append(f"missing top-level key: {key}")

    if data.get("channelStatus") not in ("planned", "live", None):
        errors.append("channelStatus must be planned or live")

    for i, item in enumerate(data.get("news") or []):
        for field in NEWS_FIELDS:
            if field not in item:
                errors.append(f"news[{i}] missing {field}")
        if item.get("badge") not in ("resmi", "rumor"):
            errors.append(f"news[{i}] badge must be resmi or rumor")
        if item.get("badge") == "rumor" and "belum dikonfirmasi" not in str(item.get("badgeLabel", "")).lower():
            errors.append(f"news[{i}] rumor must use Belum dikonfirmasi label")
        body = item.get("body")
        if not isinstance(body, list) or not 1 <= len(body) <= 4:
            errors.append(f"news[{i}] body must be 1–4 short paragraphs")
        url = str(item.get("sourceUrl") or "")
        if not url.startswith("https://"):
            errors.append(f"news[{i}] sourceUrl must be https")

    for i, item in enumerate(data.get("schedule") or []):
        for field in SCHED_FIELDS:
            if field not in item:
                errors.append(f"schedule[{i}] missing {field}")
        if not str(item.get("sourceUrl") or "").startswith("https://"):
            errors.append(f"schedule[{i}] sourceUrl must be https")

    quiz = data.get("quiz") or {}
    qs = quiz.get("questions") or []
    if len(qs) != 5:
        errors.append("quiz must have exactly 5 questions")
    for i, q in enumerate(qs):
        choices = q.get("choices") or []
        ans = q.get("answer")
        if len(choices) != 4 or not isinstance(ans, int) or not 0 <= ans < 4:
            errors.append(f"quiz[{i}] needs 4 choices and a valid answer index")

    vote = data.get("vote") or {}
    if not vote.get("id") or not vote.get("options"):
        errors.append("vote needs id and options")

    blob = json.dumps(data, ensure_ascii=False).lower()
    for word in BANNED:
        if word in blob:
            errors.append(f"anonymity check failed: found {word!r}")

    if errors:
        print("INVALID")
        for err in errors:
            print(" -", err)
        return 1

    print(f"OK  {path}")
    print(f"  news={len(data['news'])}  schedule={len(data['schedule'])}  quiz=5  vote_options={len(vote['options'])}")
    print(f"  updatedAt={data['updatedAt']}")
    return 0


def _ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    return ctx


def fetch_rss(url: str, limit: int = 30) -> list[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "KabarUnnieBot/1.0 (editorial refresh; +https://t.me/kabarunnie)"})
    with urllib.request.urlopen(req, timeout=20, context=_ssl_ctx()) as resp:
        raw = resp.read()
    root = ET.fromstring(raw)
    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or item.findtext("pubdate") or "").strip()
        if title and link:
            items.append({"title": title, "link": link, "pubDate": pub})
        if len(items) >= limit:
            break
    return items


def is_relevant(title: str) -> bool:
    t = title.lower()
    return any(k in t for k in KEYWORDS)


def headlines() -> int:
    DRAFT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = DRAFT_DIR / f"headlines-{stamp}.md"
    try:
        items = fetch_rss(HERALD_RSS)
    except Exception as exc:
        print(f"Failed to fetch {HERALD_RSS}: {exc}", file=sys.stderr)
        return 1

    relevant = [it for it in items if is_relevant(it["title"])]
    lines = [
        f"# Draft headlines ({stamp} UTC)",
        "",
        "Sumber RSS: The Korea Herald K-pop",
        f"<{HERALD_RSS}>",
        "",
        "Ini daftar judul mentah. Jangan langsung masukkan ke aplikasi.",
        "Tulis ulang dalam bahasa Indonesia (maks. 3 kalimat), tambahkan tautan,",
        "dan tandai Sumber resmi atau Belum dikonfirmasi, lalu sunting content.json.",
        "",
        "## Yang relevan (kata kunci girl group / idol wanita)",
        "",
    ]
    if not relevant:
        lines.append("_Tidak ada judul yang cocok kata kunci pada unduhan ini._")
        lines.append("")
    for it in relevant:
        lines.append(f"- {it['title']}")
        lines.append(f"  {it['link']}")
        if it["pubDate"]:
            lines.append(f"  {it['pubDate']}")
        lines.append("")
    lines += ["## Semua item RSS", ""]
    for it in items:
        mark = " ★" if it in relevant else ""
        lines.append(f"- {it['title']}{mark}")
        lines.append(f"  {it['link']}")
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out} ({len(relevant)} relevant / {len(items)} total)")
    return 0


def _read_json(path: Path, default):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: Path, data, dry: bool) -> bool:
    new = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    old = path.read_text(encoding="utf-8") if path.exists() else None
    if new == old:
        return False
    if dry:
        print(f"[dry-run] would write {path.relative_to(ROOT)}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new, encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}")
    return True


def _label_wib(now: datetime) -> str:
    w = now.astimezone(WIB)
    return f"{HARI[w.weekday()]}, {w.day} {BULAN[w.month - 1]} {w.year}"


def refresh(dry: bool) -> int:
    # 1) raw RSS inbox (editor input only; not read by the app)
    try:
        items = [it for it in fetch_rss(HERALD_RSS) if is_relevant(it["title"])]
        inbox = {"source": HERALD_RSS, "note": "Raw headlines. Rewrite + label before approving.", "items": items}
        _write_json(INBOX, inbox, dry)
    except Exception as exc:  # network errors must not break the run
        print(f"warn: RSS fetch failed: {exc}", file=sys.stderr)

    # 2) promote approved items
    data = load_content()
    ids = {n["id"] for n in data["news"]}
    approved = sorted(APPROVED_DIR.glob("*.json")) if APPROVED_DIR.exists() else []
    added = []
    for f in approved:
        item = _read_json(f, None)
        if not isinstance(item, dict):
            print(f"skip {f.name}: not an object", file=sys.stderr)
            continue
        missing = [k for k in NEWS_FIELDS if k not in item]
        if missing or not str(item.get("sourceUrl", "")).startswith("https://"):
            print(f"skip {f.name}: missing {missing or 'https sourceUrl'}", file=sys.stderr)
            continue
        if item["id"] in ids:
            print(f"skip {f.name}: id {item['id']} already in content.json")
        else:
            added.append(item)
            ids.add(item["id"])
        if not dry:
            f.unlink()
    if added:
        added.sort(key=lambda n: n.get("publishedAt", ""), reverse=True)
        data["news"] = (added + data["news"])[:MAX_NEWS]
        now = datetime.now(timezone.utc)
        data["updatedAt"] = now.astimezone(WIB).isoformat(timespec="minutes")
        data["todayLabel"] = _label_wib(now)
        print(f"promoted {len(added)} item(s): {', '.join(n['id'] for n in added)}")
        _write_json(CONTENT, data, dry)
    else:
        print("no approved items to promote")
    if dry and added:
        return 0
    return validate()


def _tg(token: str, method: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30, context=_ssl_ctx()) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        try:
            return json.load(exc)
        except Exception:
            return {"ok": False, "error_code": exc.code, "description": str(exc)}


def _esc(t) -> str:
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _app_link(app_url: str, item_id: str) -> str:
    if not app_url:
        return ""
    sep = "&" if "?" in app_url else "?"
    if "t.me/" in app_url:  # direct Mini App link: t.me/<bot>/<app>?startapp=<id>
        return f"{app_url}{sep}startapp={urllib.parse.quote(item_id)}"
    return f"{app_url}{sep}screen=detail&id={urllib.parse.quote(item_id)}"


def build_message(n: dict, chat_id: str, app_url: str, handle: str) -> dict:
    label = "Belum dikonfirmasi" if n.get("badge") == "rumor" else "Sumber resmi"
    lines = [f"<b>{_esc(n['title'])}</b>", "", _esc(n["hook"]), ""]
    lines.append(f"<i>{label}</i> · <a href=\"{_esc(n['sourceUrl'])}\">{_esc(n['sourceName'])}</a>")
    media = n.get("media") or {}
    if media.get("url"):
        lines.append(f"▶ <a href=\"{_esc(media['url'])}\">Video resmi · {_esc(media.get('channel', 'YouTube'))}</a>")
    xp = n.get("xPost") or {}
    if xp.get("url"):
        lines.append(f"𝕏 <a href=\"{_esc(xp['url'])}\">{_esc(xp.get('handle', 'Post resmi'))}</a>")
    lines += ["", _esc(handle)]
    payload = {"chat_id": chat_id, "text": "\n".join(lines), "parse_mode": "HTML"}
    if media.get("url"):
        # Telegram renders the official video's own preview; nothing is uploaded.
        payload["link_preview_options"] = {"url": media["url"], "prefer_large_media": True, "show_above_text": True}
    else:
        payload["link_preview_options"] = {"is_disabled": True}
    row = []
    link = _app_link(app_url, n["id"])
    if link:
        row.append({"text": "Buka App", "url": link})
    if media.get("url"):
        row.append({"text": "▶ Tonton", "url": media["url"]})
    if row:
        payload["reply_markup"] = {"inline_keyboard": [row]}
    return payload


def post(dry: bool) -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHANNEL_ID", "").strip()
    app_url = os.environ.get("APP_URL", "").strip()
    max_posts = int(os.environ.get("MAX_POSTS", "5") or 5)
    if not dry and (not token or not chat_id):
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHANNEL_ID not set: skipping post step.")
        return 0
    if not app_url:
        print("warn: APP_URL not set; posts will have no 'Buka App' button.")
    data = load_content()
    posted = _read_json(POSTED, {"posted": []})
    done = set(posted.get("posted", []))
    todo = [n for n in reversed(data["news"]) if n["id"] not in done][:max_posts]  # oldest first
    if not todo:
        print("nothing new to post")
        return 0
    for n in todo:
        payload = build_message(n, chat_id or "@channel", app_url, data.get("handle", ""))
        if dry:
            print(f"[dry-run] would post {n['id']}:")
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            continue
        res = _tg(token, "sendMessage", payload)
        if not res.get("ok") and res.get("error_code") == 429:
            wait = int((res.get("parameters") or {}).get("retry_after", 5))
            time.sleep(min(wait, 60))
            res = _tg(token, "sendMessage", payload)
        if not res.get("ok"):
            print(f"post failed for {n['id']}: {res.get('error_code')} {res.get('description')}", file=sys.stderr)
            break  # keep remaining items for the next run
        done.add(n["id"])
        posted["posted"] = sorted(done)
        _write_json(POSTED, posted, False)  # save after each success: never double-post
        print(f"posted {n['id']}")
        time.sleep(3)
    return 0


def seed(dry: bool) -> int:
    data = load_content()
    posted = _read_json(POSTED, {"posted": []})
    posted["posted"] = sorted(set(posted.get("posted", [])) | {n["id"] for n in data["news"]})
    _write_json(POSTED, posted, dry)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Kabar Unnie content helper")
    parser.add_argument("command", choices=("validate", "headlines", "refresh", "post", "seed"))
    parser.add_argument("--dry-run", action="store_true", help="change nothing, send nothing")
    args = parser.parse_args()
    if args.command == "validate":
        return validate()
    if args.command == "refresh":
        return refresh(args.dry_run)
    if args.command == "post":
        return post(args.dry_run)
    if args.command == "seed":
        return seed(args.dry_run)
    return headlines()


if __name__ == "__main__":
    sys.exit(main())
