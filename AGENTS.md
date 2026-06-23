# Agent Guidance

## Project Overview

Crypto Open Interest Dashboard — a FastAPI + SQLAlchemy dashboard for futures Open Interest (OI) across Binance, Bybit, and Coinglass.

## Data Sources

- **Bybit** (`data_sources/bybit_source.py`): free, full history since ~2020, supports 5m/15m/1h/4h/1d.
- **Binance** (`data_sources/binance_source.py`): free, OI history limited to ~last 30 days, supports 5m/15m/1h/4h/1d.
- **Coinglass** (`data_sources/coinglass_source.py`): paid API key. Hobbyist plan supports only `4h/6h/8h/12h/1d/1w`. `<4h` intervals return `403`.

## Sync Strategy

- `sync_service.py` is the core backfill/incremental engine.
- `sync_intervals.py` is the CLI batch backfill tool: `python sync_intervals.py <source> --intervals 4h 1h 15m 5m`.
- Default retention (see `config.py`):
  - 4h → 365 days
  - 1h/15m/5m → 30 days
  - 1d/1w/1M → since onboard date
- Environment variables in `.env` can override `BACKFILL_DAYS_*` values.

## Known Limitations

1. **Coinglass high-frequency OI**: Hobbyist API plan does not support `1h/15m/5m`. The dashboard fills these intervals from Bybit and Binance instead.
2. **Bybit rate limiting**: large backfills may hit `10006 Too many visits`. The source client has exponential backoff retries.
3. **SQLite concurrency**: avoid running multiple `sync_intervals.py` processes simultaneously; they contend for the database write lock.
4. **Binance 30-day window**: `futures/data/openInterestHist` only returns the most recent ~30 days regardless of requested range.

## When Modifying

- Keep minimal changes; preserve existing coding style.
- Update `README.md` and this file if data-source behavior or sync defaults change.
- Run `python sync_intervals.py <source> --intervals <interval>` to validate after touching fetch logic.
