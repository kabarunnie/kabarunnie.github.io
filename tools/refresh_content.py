#!/usr/bin/env python3
"""Kabar Unnie content helper (runs locally and in GitHub Actions).

Commands:
  validate   Check app/data/content.json against the schema.
  headlines  Fetch public RSS headlines and write tools/drafts/headlines-*.md.
  refresh    CI job: fetch RSS into data/inbox.json (raw, never shown in the
             app), promote editor-approved items from data/approved/*.json
             into app/data/content.json, then validate.
  post       Post news items not yet in data/posted.json to the Telegram
             channel via the Bot API as a photo post: sendPhoto with the
             official image *URL* (Telegram fetches it; nothing is stored or
             re-hosted here) + an HTML caption (<=1024 chars) that carries the
             official YouTube video link and the source link.
             Skips cleanly when TELEGRAM_BOT_TOKEN / TELEGRAM_CHANNEL_ID are
             missing.
  seed       Mark every current news item as already posted.
  poll       Post at most one native Telegram poll or quiz (sendPoll) to the
             channel per WIB day. Uses content.json channelPoll if present,
             otherwise a quiz question from the daily kuis. Skips cleanly when
             a poll was already sent today or Telegram secrets are missing.
             Optional 'Buka App' button on the poll, or a single follow-up
             message if the API rejects reply_markup on sendPoll.

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


# Every NEW channel post must carry an official image + an official video.
#   "image": {"url": "https://...jpg|png", "credit": "Instagram @official", "source": "https://page-where-it-is-published"}
#   "video": {"url": "https://www.youtube.com/watch?v=ID", "title": "...", "channel": "SMTOWN",
#             "official": true, "relation": "MV terbaru Hearts2Hearts"}
# Images are passed to Telegram by URL only; never downloaded into the repo.
IMAGE_FIELDS = ("url", "credit", "source")
VIDEO_FIELDS = ("url", "title", "channel", "relation")
IMAGE_TYPES = ("image/jpeg", "image/png")
TG_PHOTO_URL_MAX = 5 * 1024 * 1024  # Bot API limit for photos sent by URL
CAPTION_MAX = 1024
UA = "KabarUnnieBot/1.0 (+https://t.me/kabarunnie)"


def youtube_id(url: str) -> str:
    u = urllib.parse.urlparse(str(url or ""))
    host = (u.hostname or "").lower()
    if host in ("youtu.be",):
        return u.path.strip("/").split("/")[0]
    if host in ("www.youtube.com", "youtube.com", "m.youtube.com", "music.youtube.com"):
        if u.path == "/watch":
            return (urllib.parse.parse_qs(u.query).get("v") or [""])[0]
        parts = [x for x in u.path.split("/") if x]
        if len(parts) >= 2 and parts[0] in ("shorts", "embed", "live"):
            return parts[1]
    return ""


def media_errors(item: dict) -> list[str]:
    """Offline schema check for the required image + video (no network)."""
    errs = []
    img = item.get("image")
    if not isinstance(img, dict):
        errs.append("missing image {url, credit, source}")
    else:
        for k in IMAGE_FIELDS:
            if not str(img.get(k) or "").strip():
                errs.append(f"image.{k} missing")
        for k in ("url", "source"):
            if img.get(k) and not str(img[k]).startswith("https://"):
                errs.append(f"image.{k} must be https")
        if "i.ytimg.com" in str(img.get("url", "")) or "img.youtube.com" in str(img.get("url", "")):
            errs.append("image.url must be an official photo, not the video thumbnail")
    vid = item.get("video")
    if not isinstance(vid, dict):
        errs.append("missing video {url, title, channel, relation}")
    else:
        for k in VIDEO_FIELDS:
            if not str(vid.get(k) or "").strip():
                errs.append(f"video.{k} missing")
        if not youtube_id(vid.get("url", "")):
            errs.append("video.url must be a YouTube video link")
        if vid.get("official") is not True:
            errs.append("video.official must be true (official agency/artist/broadcaster channel)")
    return errs


def _open(url: str, method: str = "GET", timeout: int = 20):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": UA, "Accept": "*/*"})
    return urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx())


def check_image_url(url: str) -> str:
    """'' if Telegram should be able to fetch it as a photo, else the reason."""
    try:
        with _open(url) as resp:
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            size = int(resp.headers.get("Content-Length") or 0)
            if resp.status != 200:
                return f"HTTP {resp.status}"
            if ctype not in IMAGE_TYPES:
                return f"content-type {ctype or '?'} (need jpeg/png)"
            if not size:
                size = len(resp.read(TG_PHOTO_URL_MAX + 1))
            if size > TG_PHOTO_URL_MAX:
                return f"too large ({size} bytes > 5 MB)"
    except urllib.error.HTTPError as exc:
        return f"HTTP {exc.code}"
    except Exception as exc:
        return f"fetch failed: {exc}"
    return ""


def check_video_url(video: dict) -> str:
    """'' if YouTube oEmbed resolves and the uploader matches video.channel."""
    vid = youtube_id(video.get("url", ""))
    if not vid:
        return "not a YouTube link"
    q = urllib.parse.quote(f"https://www.youtube.com/watch?v={vid}", safe="")
    try:
        with _open(f"https://www.youtube.com/oembed?format=json&url={q}") as resp:
            meta = json.load(resp)
    except urllib.error.HTTPError as exc:
        return f"oEmbed HTTP {exc.code} (private/removed/not embeddable?)"
    except Exception as exc:
        return f"oEmbed failed: {exc}"
    author = str(meta.get("author_name") or "").strip()
    if author.casefold() != str(video.get("channel") or "").strip().casefold():
        return f"uploader is {author!r}, not {video.get('channel')!r}"
    return ""


def media_live_errors(item: dict) -> list[str]:
    errs = media_errors(item)
    if errs:
        return errs
    r = check_image_url(item["image"]["url"])
    if r:
        errs.append(f"image.url not usable: {r}")
    r = check_video_url(item["video"])
    if r:
        errs.append(f"video.url not usable: {r}")
    return errs


def _warn(msg: str) -> None:
    # ::warning:: shows up as an annotation on the Actions run page.
    print(f"::warning::{msg}" if os.environ.get("GITHUB_ACTIONS") else f"warn: {msg}", file=sys.stderr)


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

    posted_ids = set(_read_json(POSTED, {"posted": []}).get("posted", []))
    for i, item in enumerate(data.get("news") or []):
        if item.get("id") not in posted_ids or "image" in item or "video" in item:
            # Not yet on the channel (or already carries media): image + video required.
            for err in media_errors(item):
                errors.append(f"news[{i}] {item.get('id')}: {err}")
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
    bonus = quiz.get("bonus")
    if bonus:
        choices = bonus.get("choices") or []
        ans = bonus.get("answer")
        if not bonus.get("q") or len(choices) != 4 or not isinstance(ans, int) or not 0 <= ans < 4:
            errors.append("quiz.bonus needs a question, 4 choices, and a valid answer index")

    poll = data.get("channelPoll")
    if poll:
        opts = poll.get("options") or []
        if not poll.get("id") or not poll.get("question"):
            errors.append("channelPoll needs id and question")
        if not (2 <= len(opts) <= 12):
            errors.append("channelPoll needs 2–12 options")
        if any(len(str(o)) < 1 or len(str(o)) > 100 for o in opts):
            errors.append("channelPoll option must be 1–100 characters")
        if len(str(poll.get("question") or "")) > 300:
            errors.append("channelPoll question must be at most 300 characters")
        kind = poll.get("type") or "regular"
        if kind not in ("regular", "quiz"):
            errors.append("channelPoll type must be regular or quiz")
        if kind == "quiz":
            ans = poll.get("correct")
            if not isinstance(ans, int) or not 0 <= ans < len(opts):
                errors.append("channelPoll quiz needs a valid correct index")

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
    bonus_n = 1 if (quiz.get("bonus") or {}).get("q") else 0
    poll_n = 1 if (data.get("channelPoll") or {}).get("id") else 0
    print(f"  news={len(data['news'])}  schedule={len(data['schedule'])}  quiz=5  bonus={bonus_n}  vote_options={len(vote['options'])}  channelPoll={poll_n}")
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
        if item["id"] not in ids:
            merrs = media_live_errors(item)
            if merrs:
                # Held: the file stays in data/approved/ until image + video are fixed.
                _warn(f"HOLD {f.name}: " + "; ".join(merrs))
                continue
        if item["id"] in ids:
            print(f"skip {f.name}: id {item['id']} already in content.json")
        else:
            added.append(item)
            ids.add(item["id"])
        if not dry:
            f.unlink()
    now = datetime.now(timezone.utc)
    today = _label_wib(now)
    if added:
        added.sort(key=lambda n: n.get("publishedAt", ""), reverse=True)
        data["news"] = (added + data["news"])[:MAX_NEWS]
        data["updatedAt"] = now.astimezone(WIB).isoformat(timespec="minutes")
        data["todayLabel"] = today
        print(f"promoted {len(added)} item(s): {', '.join(n['id'] for n in added)}")
        _write_json(CONTENT, data, dry)
    else:
        print("no approved items to promote")
        # Always stamp today's WIB label so the JSON date does not go stale
        # when there is nothing new to publish. The app also computes this
        # client-side; this keeps content.json in sync after each run.
        if data.get("todayLabel") != today:
            data["todayLabel"] = today
            print(f"todayLabel -> {today}")
            _write_json(CONTENT, data, dry)
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


def _visible_len(html: str) -> int:
    """Caption length as Telegram counts it (text after entity parsing, UTF-16)."""
    import html as _h
    import re
    text = _h.unescape(re.sub(r"<[^>]+>", "", html))
    return len(text.encode("utf-16-le")) // 2


def build_message(n: dict, chat_id: str, app_url: str, handle: str) -> dict:
    """sendPhoto payload: official image by URL + caption with video + source links."""
    label = "Belum dikonfirmasi" if n.get("badge") == "rumor" else "Sumber resmi"
    img = n["image"]
    vid = n["video"]
    vurl = f"https://www.youtube.com/watch?v={youtube_id(vid['url'])}"

    def caption(title: str, hook: str) -> str:
        lines = [f"<b>{_esc(title)}</b>"]
        if hook:
            lines += ["", _esc(hook)]
        lines += [
            "",
            f"▶ <a href=\"{_esc(vurl)}\">{_esc(vid['relation'])}</a> · {_esc(vid['channel'])} (YouTube resmi)",
            f"<i>{label}</i> · <a href=\"{_esc(n['sourceUrl'])}\">{_esc(n['sourceName'])}</a>",
            f"📷 <a href=\"{_esc(img['source'])}\">Foto: {_esc(img['credit'])}</a>",
        ]
        xp = n.get("xPost") or {}
        if xp.get("url"):
            lines.append(f"𝕏 <a href=\"{_esc(xp['url'])}\">{_esc(xp.get('handle', 'Post resmi'))}</a>")
        if handle:
            lines += ["", _esc(handle)]
        return "\n".join(lines)

    title, hook = n["title"], n.get("hook", "")
    cap = caption(title, hook)
    while _visible_len(cap) > CAPTION_MAX and hook:
        words = hook.split()
        hook = " ".join(words[:-3]) + "…" if len(words) > 3 else ""
        cap = caption(title, hook)
    while _visible_len(cap) > CAPTION_MAX and len(title) > 40:
        title = title[: len(title) - 20].rstrip() + "…"
        cap = caption(title, hook)

    payload = {"chat_id": chat_id, "photo": img["url"], "caption": cap, "parse_mode": "HTML"}
    row = []
    link = _app_link(app_url, n["id"])
    if link:
        row.append({"text": "Buka App", "url": link})
    row.append({"text": "▶ Tonton", "url": vurl})
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
    held = 0
    for n in todo:
        # Hard gate: no photo + official video, no post (item stays unposted).
        merrs = media_live_errors(n)
        if merrs:
            _warn(f"HOLD {n['id']} (not posted): " + "; ".join(merrs))
            held += 1
            continue
        payload = build_message(n, chat_id or "@channel", app_url, data.get("handle", ""))
        if dry:
            print(f"[dry-run] would sendPhoto {n['id']} (caption {_visible_len(payload['caption'])}/{CAPTION_MAX}):")
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            continue
        res = _tg(token, "sendPhoto", payload)
        if not res.get("ok") and res.get("error_code") == 429:
            wait = int((res.get("parameters") or {}).get("retry_after", 5))
            time.sleep(min(wait, 60))
            res = _tg(token, "sendPhoto", payload)
        if not res.get("ok"):
            _warn(f"post failed for {n['id']}: {res.get('error_code')} {res.get('description')}")
            if res.get("error_code") == 400:
                held += 1
                continue  # e.g. Telegram could not fetch the photo URL: hold this one only
            break  # keep remaining items for the next run
        msg = res.get("result") or {}
        if not msg.get("photo"):
            _warn(f"{n['id']}: Telegram accepted the post but returned no photo")
        done.add(n["id"])
        posted["posted"] = sorted(done)
        _write_json(POSTED, posted, False)  # save after each success: never double-post
        print(f"posted {n['id']} (photo + video link)")
        time.sleep(3)
    if held:
        print(f"{held} item(s) held: need a working official image URL + official YouTube video")
    return 0


def _bot_token() -> str:
    # Actions uses TELEGRAM_BOT_TOKEN; local ops may use KABARUNNIE_BOT_TOKEN.
    # Never print either value.
    return (
        os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        or os.environ.get("KABARUNNIE_BOT_TOKEN", "").strip()
    )


def _poll_state(posted: dict) -> list:
    polls = posted.get("polls")
    return polls if isinstance(polls, list) else []


def _today_wib(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(WIB).date().isoformat()


def _build_daily_poll(data: dict, today: str, used_ids: set[str], used_questions: set[str]) -> dict | None:
    """Pick today's sendPoll payload. Prefer a fresh channelPoll; else a kuis item."""
    raw = data.get("channelPoll") or {}
    cid = str(raw.get("id") or "")
    if cid and cid not in used_ids and raw.get("question") and raw.get("options"):
        return {
            "id": cid,
            "type": raw.get("type") or "regular",
            "question": str(raw["question"]),
            "options": [str(o) for o in raw["options"]],
            "correct": raw.get("correct"),
            "explanation": raw.get("explanation") or "",
        }
    qs = (data.get("quiz") or {}).get("questions") or []
    if len(qs) >= 2:
        start = datetime.fromisoformat(today).timetuple().tm_yday % len(qs)
        for offset in range(len(qs)):
            idx = (start + offset) % len(qs)
            q = qs[idx]
            question = str(q.get("q") or "")
            if not question or question in used_questions:
                continue
            return {
                "id": f"quiz-{today}-{idx}",
                "type": "quiz",
                "question": question,
                "options": [str(o) for o in (q.get("choices") or [])],
                "correct": q.get("answer"),
                "explanation": "Sumber: fakta publik yang sudah dimuat di Kabar Unnie.",
            }
    return None


def poll(dry: bool) -> int:
    """At most one native poll/quiz per WIB day. No-op if already sent today."""
    today = _today_wib()
    posted = _read_json(POSTED, {"posted": []})
    polls = _poll_state(posted)
    if any(p.get("date") == today for p in polls if isinstance(p, dict)):
        print(f"poll already sent today ({today}); skipping")
        return 0

    data = load_content()
    used_ids = {str(p.get("id")) for p in polls if isinstance(p, dict) and p.get("id")}
    used_questions = set()
    cutoff = (datetime.fromisoformat(today) - timedelta(days=7)).date()
    for pinfo in polls:
        if not isinstance(pinfo, dict):
            continue
        if pinfo.get("question"):
            used_questions.add(str(pinfo["question"]))
        d = str(pinfo.get("date") or "")
        try:
            if d and datetime.fromisoformat(d).date() >= cutoff and pinfo.get("id"):
                # Same quiz stem may be reused after the editor rotates questions.
                pass
        except ValueError:
            pass
    item = _build_daily_poll(data, today, used_ids, used_questions)
    if not item or not item["question"] or len(item["options"]) < 2:
        print("no new channelPoll or quiz available; skipping daily poll")
        return 0

    token = _bot_token()
    chat_id = (os.environ.get("TELEGRAM_CHANNEL_ID", "").strip() or "@kabarunnie")
    app_url = (os.environ.get("APP_URL", "").strip() or "https://t.me/Kabarunnie_bot/app")
    if not dry and not token:
        print("TELEGRAM_BOT_TOKEN / KABARUNNIE_BOT_TOKEN not set: skipping poll step.")
        return 0

    payload = {
        "chat_id": chat_id,
        "question": item["question"],
        "options": item["options"],
        "is_anonymous": True,
        "type": "quiz" if item["type"] == "quiz" else "regular",
        "allows_multiple_answers": False,
    }
    if payload["type"] == "quiz":
        payload["correct_option_id"] = int(item["correct"])
        if item.get("explanation"):
            payload["explanation"] = item["explanation"][:200]
    if app_url:
        payload["reply_markup"] = {
            "inline_keyboard": [[{"text": "Buka App", "url": app_url}]]
        }

    if dry:
        kind = payload["type"]
        print(f"[dry-run] would sendPoll ({kind}) {item['id']}: {item['question']}")
        for i, opt in enumerate(item["options"]):
            mark = " <<" if kind == "quiz" and i == item.get("correct") else ""
            print(f"  {i}. {opt}{mark}")
        return 0

    res = _tg(token, "sendPoll", payload)
    follow_id = None
    if not res.get("ok") and app_url and "reply_markup" in payload:
        # Some clients reject buttons on polls; send the poll alone, then one follow-up.
        desc = str(res.get("description") or "")
        if "reply_markup" in desc.lower() or res.get("error_code") == 400:
            payload.pop("reply_markup", None)
            res = _tg(token, "sendPoll", payload)
            if res.get("ok"):
                follow = _tg(
                    token,
                    "sendMessage",
                    {
                        "chat_id": chat_id,
                        "text": "Lanjut di aplikasi: kuis, vote, dan Kata Unnie.",
                        "reply_markup": {
                            "inline_keyboard": [[{"text": "Buka App", "url": app_url}]]
                        },
                    },
                )
                if follow.get("ok"):
                    follow_id = (follow.get("result") or {}).get("message_id")
                else:
                    _warn("poll follow-up with Buka App failed; poll itself was sent")

    if not res.get("ok"):
        _warn(f"poll failed: {res.get('error_code')} {res.get('description')}")
        return 1

    msg = res.get("result") or {}
    mid = msg.get("message_id")
    polls.append(
        {
            "id": item["id"],
            "date": today,
            "type": item["type"],
            "question": item["question"],
            "message_id": mid,
            "followup_id": follow_id,
        }
    )
    posted["polls"] = polls
    _write_json(POSTED, posted, False)
    print(f"posted poll {item['id']} message_id={mid}")
    return 0


def seed(dry: bool) -> int:
    data = load_content()
    posted = _read_json(POSTED, {"posted": []})
    posted["posted"] = sorted(set(posted.get("posted", [])) | {n["id"] for n in data["news"]})
    _write_json(POSTED, posted, dry)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Kabar Unnie content helper")
    parser.add_argument("command", choices=("validate", "headlines", "refresh", "post", "seed", "poll"))
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
    if args.command == "poll":
        return poll(args.dry_run)
    return headlines()


if __name__ == "__main__":
    sys.exit(main())
