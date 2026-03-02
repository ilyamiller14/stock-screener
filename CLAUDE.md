# stock-screener — Claude Code Instructions

## Deploy

```bash
npm run build && wrangler pages deploy dist --project-name=stock-screener --branch=production
```

MUST use `--branch=production` or it deploys to preview only.

## Live URL

https://stock-screener.pages.dev (configure in Cloudflare dashboard)

## Python Screener

Run locally (dry run — no email sent):
```bash
python -m screener.main --dry-run
```

Run with email:
```bash
GMAIL_USER=you@gmail.com GMAIL_APP_PASSWORD=xxxx EMAIL_RECIPIENTS=you@gmail.com python -m screener.main
```

## Architecture

- Python screener runs daily via GitHub Actions (`.github/workflows/daily_screen.yml`)
- Results written to `results/latest.json` and committed back to the repo
- React frontend reads `latest.json` from GitHub raw CDN (`VITE_RESULTS_URL` env var)
- Cloudflare Pages auto-deploys on push to `main`

## GitHub Secrets Required

| Secret | Description |
|--------|-------------|
| `GMAIL_USER` | Gmail sender address |
| `GMAIL_APP_PASSWORD` | App-specific password from myaccount.google.com/apppasswords |
| `EMAIL_RECIPIENTS` | Comma-separated recipient emails |
| `GITHUB_TOKEN` | Auto-provided by Actions |

## Key Files

- `screener/config.py` — all scoring weights and thresholds
- `screener/indicators.py` — all technical indicator formulas
- `screener/scorer.py` — composite scoring logic
- `results/latest.json` — schema read by the React frontend

## No Mock Data

All indicator values must come from yfinance OHLCV data, computed by our own code. Never hardcode expected values or fabricate results.
