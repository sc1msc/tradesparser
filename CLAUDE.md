# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A set of standalone Python scripts that scrape bankruptcy car auction lots (Moscow + Moscow Oblast) from a Next.js trade-aggregator site, enrich them with VIN decoding, mileage, and market valuations (Auto.ru, optionally TRONK/Avito), build themed selections, and publish a digest to a Telegram channel via Telegraph. **The only shared state between scripts is one Google Spreadsheet** (`config.SPREADSHEET_ID`), accessed through a service account (`service_account.json`).

Code comments, docstrings, and console output are in Russian. Every module has a long docstring explaining *why* it works the way it does. Read it before changing a script. Match that style.

## Commands

No build, lint, or test suite. There is no git repo either. Each script runs directly and exposes a `run()` function:

```
pip install -r requirements.txt
playwright install chromium           # browser for evaluate_autoru_browser.py / evaluate_avito_browser.py
python sheets_writer.py               # check the Google Sheets connection
python run_pipeline.py                # full data pipeline (see order below)
python main.py                        # any single step can also run on its own
python send_digest.py                 # publish to Telegram (manual, interactive choice of selection)
python tronk_valuation.py <VIN>       # one-off paid TRONK test, does not write to the sheet
```

Several steps prompt for `yes`/`да` confirmation on stdin (paid API calls, launching the browser). They cannot run non-interactively without that input. Playwright scripts run with `headless=False` on purpose (anti-bot) and may pause so a human can solve a captcha.

## Data flow (sheets = pipeline stages)

```
main.py ──► "lots" (raw, A..AM via sheets_writer + extra cols; AZ/BA/BB = brand/name/date from autodoc_decode.py)
              │  fill_missing_mileage.py (paid TRONK probeg) writes mileage back into "lots"
              ▼
build_lots_processed.py ──► "lots_processed"   (FULL overwrite from "lots" every run; empty
              │                  brand/name/year filled from title via fill_missing_from_title.fill_rows)
              ▼
build_lots_current_month.py ──► "lots_current_month"  (applications_end within 30 days;
              │                  preserves extra/trailing columns by VIN across rebuilds)
              │  evaluate_autoru_browser.py adds autoru_* columns here (Playwright)
              ▼
build_lot_selections.py ──► "lots_top_gap", "lots_budget_1m", "lots_one_owner", ...
              ▼
send_digest.py ──► Telegram channel + Telegraph page (telegraph_publish.py)
```

`run_pipeline.py` runs the steps in a fixed order, and **the order matters**:
- The title-based brand/name/year fill used to be a separate step after `build_lots_processed`, and any standalone rebuild wiped it. It now runs inside `build_lots_processed`; `fill_missing_from_title.py` alone is only for manual use.
- `evaluate_autoru_browser` reads `mileage_km` from `lots_current_month`, so it must run after the mileage fill and both rebuilds.

Step 7 (the last) of `run_pipeline.py` is `export_to_miniapp.py`: it reads `lots_current_month`, downloads each lot card from the trade site for data the sheet lacks (all photos, the public-offer price schedule `bidding_periods`, trade form, status), caches it in `miniapp_details_cache.json` (gitignored, refreshed after `MINIAPP_DETAILS_REFRESH_DAYS`), and POSTs everything to the mini app server. It skips itself when `MINIAPP_API_URL`/`MINIAPP_IMPORT_TOKEN` are not set and never fails the pipeline.

Not in the pipeline (manual/side tools): `autodoc_decode.py` (VIN → Autodoc, writes brand/model/date into `lots` from column AZ, has its own inline config), `evaluate_tronk.py` / `evaluate_avito_browser.py` (their outputs are no longer read downstream; Auto.ru is the only market price used), `filter_beautiful_plates_gspread.py` (uses `plates_series.txt`, writes a `beautiful_plates` tab + xlsx), and `temp.py` (scratch).

## Key conventions and gotchas

- **`sheets_writer.py` schema is stale.** Its `COLUMNS` (A..AM) is used only by `main.py`, `evaluate_tronk.py`, and `evaluate_avito_browser.py`. The real `lots` sheet has more columns. Newer scripts (`build_*`, `fill_*`, `evaluate_autoru_browser`) bypass it and use gspread directly, addressing columns by header name or explicit column letter. Follow that pattern in new code. `ARCHITECTURE.md` describes the older three-stage design and doesn't cover the newer scripts.
- `sheets_writer.ensure_header()` rewrites row 1 of `lots` on connect. `SheetState` writes explicit ranges (`A5:AM5`) instead of relying on Sheets table auto-detection, which previously caused column shifts.
- `main.py` deletes lots whose application deadline passed `EXPIRED_LOT_DAYS` ago and skips `lot_id`s already in the sheet, so re-runs are idempotent.
- Scraping (`nextjs_json.py`): lot data is JSON embedded in `self.__next_f.push(...)` payloads, not HTML markup. `find_json_value` extracts a bracket-balanced fragment by key (`initialLots`, `initialMeta`, `lot`). Long strings (title, description) come as `"$80"` references to a separate `80:T<hex byte length>,<text>` chunk; resolve them with `resolve_text_ref`.
- Enrichment scripts write only into empty cells, or retry only rows whose status column isn't `ok`/`no_data` (`error: ...` gets retried). They leave a value empty rather than write a guess.
- **Paid APIs:** TRONK (`tronk_valuation.py`, `tronk_mileage.py`) charges per request. Per-run caps live in `config.py` (`TRONK_MAX_PER_RUN`, `MILEAGE_MAX_PER_RUN`) and are the real budget guard. Don't raise them or remove confirmation prompts casually.
- Mileage fallback used by the valuation scripts: lot card → TRONK reading extrapolated to today (`ANNUAL_MILEAGE_KM`) → `(current_year - year) * ANNUAL_MILEAGE_KM`. Mileage above `lot_metrics.MAX_PLAUSIBLE_MILEAGE_KM` (1M km) counts as missing: `fill_missing_mileage.py` marks the TRONK result `suspicious` and doesn't write `mileage_km`, and the Auto.ru step and the mini app fall back to the year estimate.
- `fill_missing_mileage.py` pays once per VIN: a VIN already checked in another row is copied for free, and duplicate VINs among candidates share one request. `MILEAGE_MAX_PER_RUN` limits unique VINs.
- Auto.ru estimates with `autoru_uncertainty_percent >= 90` or status `ambiguous` stay in selections but are labeled "оценка может быть неточной" (`lot_metrics.estimate_is_uncertain`), both in the digest (`send_digest._fmt_gap_label`) and in the mini app.
- Adding a new selection takes three edits: a `build_XXX` filter in `build_lot_selections.py`, a registration in its `BUILDERS`, and a matching `key` entry in `selections.py` (sheet name + digest texts).
- **Public offers (публичное предложение)** have a stepped price schedule. `lots.bidding_periods` holds it as compact JSON `[[bid_end, price], ...]`, while `lots.applications_end` stays the *final* deadline (used by `remove_expired_lots`): the later of the site's `stages.end_bid_time` and the last period's end (`bidding_schedule.final_deadline`), since the two don't always match. The current period's price/deadline is computed by time in `bidding_schedule.py`: `build_lots_processed.py` substitutes it into `price_current`/`applications_end`, and `send_digest.py` recomputes it at send time. `main.py` re-reads cards of ongoing public offers (skipping ones checked since the aggregator's nightly update and within `PUBLIC_OFFER_REFRESH_HOURS`) to refresh `status` (bids end the trade early), and `build_lots_current_month.py` drops closed statuses. `DATA_UPDATES.md` (Russian) explains in detail what is written once vs. refreshed, and why.
- **Numbers must be written as numbers.** gspread 6 writes RAW, so a Python string `"450000"` lands in the cell as text, and every rebuild reads sheets as strings. Before writing a sheet, call `sheets_writer.numify_rows(header, rows)` (columns listed in `sheets_writer.NUMERIC_COLUMNS`); don't switch to `USER_ENTERED` (it would turn `applications_end` into Sheets dates and `+7…` phones into numbers). `fix_numeric_cells.py` converts text-numbers already in the sheet, in place.
- `% below mkt` is computed in `build_lot_selections.py` (step 7, after the Auto.ru step) from `autoru_price_low/high` vs `price_current` and written both into `lots_current_month` (the main column users look at) and into the selection sheets. No other script fills it; a sheet formula there would be wiped by the next `build_lots_current_month` rebuild.
- Secrets are kept out of git (see `.gitignore`). The TRONK key, Telegram bot token, and `SPREADSHEET_ID` live in `local_secrets.py`, which `config.py` imports (template: `local_secrets.example.py`). Never hard-code keys into `config.py` or scripts. Also ignored: `service_account.json`, `telegraph_token.txt` (cached Telegraph token), and `browser_profile/` (the persistent Playwright Chromium profile).

## Mini app (`miniapp/`)

The Telegram Mini App "honestlot" for end users: a FastAPI + SQLite backend and a no-build vanilla JS frontend, both in one Docker image behind Caddy. See `miniapp/README.md`.
- `lot_metrics.py` (repo root) holds the one `% below mkt` formula and the damage keywords. Both `build_lot_selections.py` and the backend import it, and the Docker image copies it. Don't duplicate the formula.
- The backend also imports `bidding_schedule.py` (copied into the image like `lot_metrics.py`) and computes the current price/deadline with `effective_price_and_deadline` at request time, because a period can change between daily imports. `export_to_miniapp.py` sends status and `bidding_periods` from the sheet, and for public offers sends the *final* deadline (`final_deadline` of the card's `end_bid_time` and the schedule), not the sheet's current-period `applications_end`. The details cache is only for photos, description, trade form, platform and `end_bid_time`.
- Brand/model cleanup (aliases like VAZ→Lada, junk from title parsing) happens in `miniapp/backend/app/lots.py`, not in the sheet.
- The frontend has no build step: bump `?v=` in `miniapp/frontend/index.html` after changing `app.js`/`style.css`.
- Attribution and analytics: `users.source` is the first `start_param` (`t.me/honestlot_bot?startapp=<label>`) from signed initData; `events` stores `open`, `lot_view`, `fav_add`, `source_click`. `python -m app.stats` prints the summary. Test these locally (`miniapp/run_local.py`), not on the VM.
