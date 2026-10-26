# Stockholm Events → Telegram

Collects events happening in Greater Stockholm in the next 30 days from many sources, de-duplicates them,
translates/summarises them to English and publishes digests to a Telegram channel.

```
collectors → SQLite → filter (geo, online, tours) → dedupe → enrich (Claude) → render → Telegram
```

## Commands

```bash
python -m sthlm.cli collect [--only luma tickster ...]   # fetch sources into data/events.sqlite
python -m sthlm.cli stats                                # counts + sample
python -m sthlm.cli post daily   [--dry-run] [--test] [--no-llm]
python -m sthlm.cli post weekend [--dry-run] [--test] [--no-llm]
python -m sthlm.cli report [--send]                      # source health (to admin chat with --send)
python -m pytest -q
```

Posts are idempotent: re-running `post daily` the same day edits the existing messages instead of duplicating them.

## Sources (config.yaml)

| Source | How | Notes |
|---|---|---|
| Luma | public JSON API | tech / community / startup |
| Eventbrite | search-page JSON-LD + detail pages | wide but noisy |
| Tickster | sitemap + meta description | ~4k pages/30d nationally, cached 48 h |
| Visit Stockholm | list + detail JSON-LD | ~30 curated highlights |
| Stockholm Live | JSON-LD list | Avicii Arena, Annexet, Hovet, Södra Teatern… |
| Södra Teatern | sitemap + JSON-LD | |
| Ticketmaster | Discovery API | needs free `TICKETMASTER_API_KEY` |

Add a venue whose event pages carry schema.org/Event JSON-LD by appending one line under `sitemap_jsonld.sites`
or `jsonld_pages.pages` in `config.yaml`. No code needed.

## Setup

1. Telegram: talk to **@BotFather** → `/newbot` → copy the token. Create the channel, add the bot as **administrator**
   (permission: post / edit / delete messages). Create a second private channel for testing.
2. Copy `.env.example` → `.env` and fill the values (never commit `.env`).
3. `pip install -r requirements.txt`, then `python -m sthlm.cli collect` and `python -m sthlm.cli post daily --dry-run`.
4. Send to the test channel: `python -m sthlm.cli post daily --test` (set `TELEGRAM_TEST_CHANNEL_ID`).
5. Production: push the repo to GitHub, add the same keys as **Actions secrets**; `.github/workflows/daily.yml` runs
   daily and keeps the SQLite state on an orphan `state` branch.
