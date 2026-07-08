# JDHG Market Intelligence

Fortnightly Australian healthcare equipment market scan for JD Healthcare Group.

The workflow monitors public web sources, ARTG/regulatory signals, supplier and competitor pages, and confirmed LinkedIn company pages. It creates:

- Markdown report
- Branded PDF report
- Excel findings tracker
- source snapshot history for change detection

## Required GitHub Secrets

Add these under `Settings -> Secrets and variables -> Actions`:

- `TAVILY_API_KEY`
- `ANTHROPIC_API_KEY`

Email delivery can be added later with:

- `GMAIL_CLIENT_ID`
- `GMAIL_CLIENT_SECRET`
- `GMAIL_REFRESH_TOKEN`
- `GMAIL_SENDER`

## Manual Run

Open `Actions -> Fortnightly JDHG Market Scan -> Run workflow`.

## Schedule

The workflow is scheduled to check around 8am Sydney time on Mondays. The script enforces a fortnightly cadence from `2026-07-20`.

## Configuration

- `config/watchlist.json`: competitors, suppliers, LinkedIn URLs, search queries.
- `config/artg_keywords.json`: regulatory/product category keywords.
- `config/report_profile.json`: report sections, action labels, priority definitions.

## Notes

LinkedIn pages are used as public reference sources only. The workflow does not log into LinkedIn.
