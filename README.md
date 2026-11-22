# Kabar Unnie

Telegram Mini App + channel: girl-group & Korean entertainment news in Bahasa Indonesia.
Static site (no server, no database) hosted free on GitHub Pages, refreshed by GitHub Actions.

*Mini App Telegram + channel: berita girl group dan hiburan Korea dalam Bahasa Indonesia.
Situs statis, gratis di GitHub Pages, diperbarui otomatis oleh GitHub Actions.*

## Layout / Struktur

```
app/                  ← site root deployed to Pages (index.html, 404.html, .nojekyll, css/, js/, data/)
app/data/content.json ← everything the app shows
data/posted.json      ← ids already posted to the channel (never re-posted)
data/inbox.json       ← raw RSS headlines for editors (not shown in the app)
data/approved/        ← editor-approved items waiting to be published
tools/refresh_content.py
.github/workflows/pages.yml    ← deploy ./app on push to main
.github/workflows/refresh.yml  ← 3× daily refresh + Telegram post
```

All paths in the app are relative, so it works at `https://<user>.github.io/<repo>/` and at a domain root.
*Semua path relatif, jadi jalan di `https://<user>.github.io/<repo>/` maupun di root domain.*

## Images / Gambar

No photos are stored or uploaded. The app shows the **official YouTube thumbnail loaded directly from YouTube** and opens the official video; channel posts are text + links, and Telegram renders the official video's own link preview.
*Tidak ada foto yang disimpan atau diunggah ulang. Thumbnail dimuat langsung dari YouTube resmi; post channel berupa teks + tautan.*

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

1. Read `data/inbox.json` (raw headlines, refreshed 07:00 / 12:00 / 19:00 WIB).
2. Rewrite one item in Bahasa Indonesia (max 3 sentences), add the source link and label
   *Sumber resmi* or *Belum dikonfirmasi*, optionally `media` (official YouTube link) and `xPost` (official X post link).
   Save as `data/approved/<id>.json` (template: `data/approved/example.json.txt`).
3. Commit. The next refresh run promotes it into `app/data/content.json`, deploys Pages, and posts it to the channel once.

*Tulis ulang judul mentah dari `data/inbox.json`, simpan di `data/approved/`, commit. Run berikutnya memasukkan ke aplikasi dan memposting sekali saja.*

## Local commands

```
python3 tools/refresh_content.py validate
python3 tools/refresh_content.py refresh --dry-run
python3 tools/refresh_content.py post --dry-run     # prints the Bot API payloads, sends nothing
python3 tools/refresh_content.py seed               # mark all current items as already posted
python3 -m http.server 8000 --directory app         # open http://localhost:8000/
```

`data/posted.json` is pre-seeded with the current items so the first run does not flood the channel.
To announce them on launch, set it to `{"posted": []}`.
*`posted.json` sudah berisi item saat ini; kosongkan bila ingin mempostingnya saat peluncuran.*

## Free tier only / Hanya fitur gratis

Public repo + GitHub Pages + GitHub Actions (free minutes for public repos) + Telegram Bot API. No paid services.

Note: GitHub may pause scheduled workflows after 60 days without repository activity; any commit re-enables them.
