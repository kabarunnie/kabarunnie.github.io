# Kabar Unnie

Telegram Mini App + channel: girl-group & Korean entertainment news in Bahasa Indonesia.
Static site (no server, no database) hosted free on GitHub Pages, refreshed by GitHub Actions.

*Mini App Telegram + channel: berita girl group dan hiburan Korea dalam Bahasa Indonesia.
Situs statis, gratis di GitHub Pages, diperbarui otomatis oleh GitHub Actions.*

## Live

- Site: https://kabarunnie.github.io/ (user site repo `kabarunnie.github.io`, Pages source = GitHub Actions, deploys `./app`)
- Repo variable `APP_URL` is currently `https://kabarunnie.github.io/`; switch it to `https://t.me/<bot>/app` after the bot and Mini App exist.

## Layout / Struktur

```
app/                  ← site root deployed to Pages (index.html, 404.html, .nojekyll, css/, js/, data/)
app/data/content.json ← everything the app shows
data/posted.json      ← ids already posted to the channel (never re-posted)
data/inbox.json       ← raw RSS headlines for editors (not shown in the app)
data/approved/        ← editor-approved items waiting to be published
tools/refresh_content.py
.github/workflows/pages.yml    ← deploy ./app on push to main
.github/workflows/refresh.yml  ← 10× daily refresh + Telegram post
```

All paths in the app are relative, so it works at `https://<user>.github.io/<repo>/` and at a domain root.
*Semua path relatif, jadi jalan di `https://<user>.github.io/<repo>/` maupun di root domain.*

## Images / Gambar

Every new news item **must** have `image` (official/original photo URL + credit + source page) and `video` (official YouTube link from the agency/artist/broadcaster channel, with `relation`). Items without them are held: `refresh` keeps them in `data/approved/`, `validate` fails, and `post` skips them.
No photos are stored or uploaded: channel posts use `sendPhoto` with the image **URL** (Telegram fetches it), a caption (≤1024 chars) with the video link and source link, and the app loads the image directly from its original host with credit.
*Setiap kabar baru wajib punya foto (URL sumber asli + kredit) dan video YouTube resmi. Tidak ada foto yang disimpan atau diunggah ulang.*

## Setup (one time / sekali saja)

1. **Create a new GitHub account or organization just for this project** (do not use a personal account — the username appears in the Pages URL). Create a public repo, e.g. `kabarunnie`.
   *Buat akun/organisasi GitHub khusus proyek ini, lalu repo publik.*
2. Push this folder:
   ```
   git remote add origin https://github.com/<user>/<repo>.git
   git push -u origin main
   ```
3. **Settings → Pages → Build and deployment → Source = GitHub Actions.**
   The `Deploy Pages` workflow then publishes `./app`. URL: `https://<user>.github.io/<repo>/`.
4. **Telegram bot** — in @BotFather:
   - `/newbot` → copy the token.
   - `/newapp` → choose the bot, set the Web App URL to the Pages URL, short name e.g. `app` → direct link `https://t.me/<bot>/app`.
   - Optional: `/setmenubutton` → choose the bot → Pages URL, label `Buka App`.
5. **Channel** — create the public channel, add the bot as **admin** with *Post messages* permission.
6. **Settings → Secrets and variables → Actions**
   - Secrets: `TELEGRAM_BOT_TOKEN` (from BotFather), `TELEGRAM_CHANNEL_ID` (`@yourchannel` or the numeric `-100…` id).
     Optional `KU_BANNED_WORDS`: comma-separated words that must never appear in published data (anonymity guard).
   - Variables: `APP_URL` = `https://t.me/<bot>/app` (recommended: opens inside Telegram and deep-links to the item with `startapp`) or the Pages URL. Optional `MAX_POSTS` (default 5 per run).
7. **Settings → Actions → General → Workflow permissions = Read and write** (needed to commit `content.json` / `posted.json`).
8. Run **Actions → Refresh content → Run workflow** once with *Dry run* checked.

Without the Telegram secrets the workflow still refreshes and deploys; the post step is skipped.
*Tanpa secrets Telegram, workflow tetap jalan; langkah posting dilewati.*

## Daily editing / Alur harian

1. Read `data/inbox.json` (raw headlines, refreshed 10× daily:
   **08:00 / 10:00 / 12:00 / 14:00 / 16:00 / 18:00 / 20:00 / 21:00 / 22:00 / 23:00 KST**,
   which is **06:00 / 08:00 / 10:00 / 12:00 / 14:00 / 16:00 / 18:00 / 19:00 / 20:00 / 21:00 WIB**).
2. Rewrite one item in Bahasa Indonesia (max 3 sentences), add the source link and label
   *Sumber resmi* or *Belum dikonfirmasi*, **required** `image` + `video` (see `data/approved/README.md`), optionally `xPost` (official X post link).
   Save as `data/approved/<id>.json` (template: `data/approved/example.json.txt`).
3. Commit. The next refresh run promotes it into `app/data/content.json`, deploys Pages, and posts it to the channel once.

*Tulis ulang judul mentah dari `data/inbox.json`, simpan di `data/approved/`, commit. Run berikutnya memasukkan ke aplikasi dan memposting sekali saja.*

## Local commands

```
python3 tools/refresh_content.py validate
python3 tools/refresh_content.py refresh --dry-run
python3 tools/refresh_content.py post --dry-run     # prints the Bot API payloads, sends nothing
python3 tools/refresh_content.py poll --dry-run     # preview today's channel poll/quiz, send nothing
python3 tools/refresh_content.py seed               # mark all current items as already posted
python3 tools/app_stats.py                          # app users (GA4) + channel members
python3 -m http.server 8000 --directory app         # open http://localhost:8000/
```

`data/posted.json` is pre-seeded with the current items so the first run does not flood the channel.

Each refresh run also calls `poll`: at most **one** anonymous Telegram poll or quiz (`sendPoll`) per WIB day, recorded in `posted.json` under `polls`. Set `channelPoll` in `content.json` for an editor-written question; otherwise a daily-kuis question is used. Do not change an already-sent poll.

The Mini App can unlock an extra **Kata Unnie** comment and a bonus quiz after the user taps **Bagikan untuk buka** (Telegram share sheet to `t.me/Kabarunnie_bot/app`). Unlock is stored in `localStorage` for that WIB day only — no payment, no extra analytics.
To announce them on launch, set it to `{"posted": []}`.
*`posted.json` sudah berisi item saat ini; kosongkan bila ingin mempostingnya saat peluncuran.*


## App users / Pengguna aplikasi

Anonymous usage is counted with a free Google Analytics 4 property (no ads, no paid plan).
The Mini App sends `page_view` and `app_open` on load, plus an `in_telegram` flag and a
SHA-256 hash of the Telegram user id (never the raw id). Tracking is best-effort and
cannot break the app if it is blocked.

- Property: `properties/565453562` (display name: Kabar Unnie, timezone Asia/Jakarta)
- Measurement ID: `G-SYRMSWQCHQ`
- Query hourly / daily / total users with `python3 tools/app_stats.py`, or the GA4
  Data API / connected Analytics MCP (`run_realtime_report` for the last 30 minutes,
  `run_report` with dimension `hour` for today's hours). Standard GA4 realtime
  covers 30 minutes, not 60.

*Pengguna dihitung lewat Google Analytics 4 (gratis). ID Telegram tidak pernah dikirim mentah.*

## Free tier only / Hanya fitur gratis

Public repo + GitHub Pages + GitHub Actions (free minutes for public repos) + Telegram Bot API. No paid services.

Note: GitHub may pause scheduled workflows after 60 days without repository activity; any commit re-enables them.
