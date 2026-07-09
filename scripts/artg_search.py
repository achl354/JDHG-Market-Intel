"""Find new ARTG listings relevant to JDHG by driving the TGA's public
ARTG Search Visualisation Tool (a Power BI report embed at
https://compliance.health.gov.au/artg/ - there is no documented public API).

Approach:
1. Open the tool's "Advanced Search" page and set its "Goods Started by Date
   Range" slicer to the lookback window (a real date-range filter on the
   underlying ARTG Start Date field, confirmed via the report's Power BI
   conceptual schema).
2. Scrape the results grid (an accessible role=grid/row/gridcell table,
   virtualized - scroll to collect every row).
3. Keep only rows relevant to JDHG (product name matches a watched keyword,
   or sponsor matches a watched competitor).
4. Diff ARTG IDs against the previous run's snapshot so "new" means "not
   seen in the last scan", not just "matched a search" - mirroring the
   website-hash diffing already used in run_market_scan.py.

The Power BI date slicer is a real Angular input rejecting free text in the
wrong format (it wants "M/d/yyyy") and can pop a calendar overlay that blocks
the second field, so setting it is more fiddly than a plain form field -
see set_date_range() below.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright, Frame, Page

ARTG_URL = "https://compliance.health.gov.au/artg/"
ROOT = Path(__file__).resolve().parents[1]
ARTG_IDS_SNAPSHOT = ROOT / "data" / "source_snapshots" / "artg_ids_seen.json"

# Column order in the results grid, confirmed by inspecting the accessible
# table's role=columnheader cells.
COLUMNS = [
    "select_row",
    "artg_id",
    "product_name",
    "sponsor_name",
    "manufacturer_name",
    "public_summary",
    "product_info",
    "consumer_info",
    "active_ingredients",
]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def _get_pbi_frame(page: Page):
    for _ in range(20):
        frame = next((f for f in page.frames if "powerbi.com/reportEmbed" in f.url), None)
        if frame is not None:
            return frame
        page.wait_for_timeout(500)
    return None


def _open_advanced_search(page: Page) -> Frame | None:
    page.goto(ARTG_URL, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(4000)
    frame = _get_pbi_frame(page)
    if frame is None:
        return None
    frame.locator("[aria-label*='Advanced ARTG Search Page']").first.click(timeout=15000)
    page.wait_for_timeout(4000)
    return frame


def set_date_range(page: Page, frame: Frame, start: datetime, end: datetime) -> bool:
    """Set the 'Goods Started by Date Range' slicer. Returns True if both
    fields accepted a value without erroring (does not itself verify the
    grid actually re-filtered - callers should sanity-check row content)."""
    date_inputs = frame.locator(".date-slicer-input")
    if date_inputs.count() < 2:
        return False

    def fmt(d: datetime) -> str:
        return f"{d.month}/{d.day}/{d.year}"

    ok = True
    for i, value in ((0, fmt(start)), (1, fmt(end))):
        try:
            page.keyboard.press("Escape")
            el = date_inputs.nth(i)
            el.click(timeout=5000)
            el.fill(value, timeout=3000)
            el.press("Tab")
            page.keyboard.press("Escape")
        except Exception as exc:  # noqa: BLE001
            print(f"artg_search: failed to set date input #{i} to {value!r}: {exc}")
            ok = False
    page.wait_for_timeout(4000)
    return ok


def extract_grid_rows(frame: Frame, max_scrolls: int = 60, max_rows: int = 2000) -> list[dict[str, str]]:
    """Scrape the (virtualized) results grid, scrolling to collect rows not
    currently rendered. Bounded so a filter that silently failed to apply
    (leaving tens of thousands of rows) can't turn this into an unbounded
    scrape - hitting the cap is logged so it's visible, not silent."""
    try:
        grid = frame.locator("[role=grid]").first
        grid.wait_for(timeout=10000)
    except Exception as exc:  # noqa: BLE001
        print(f"artg_search: results grid not found: {exc}")
        return []

    seen: dict[str, dict[str, str]] = {}
    stable_rounds = 0
    for _ in range(max_scrolls):
        rows = grid.locator("[role=row]")
        count = rows.count()
        found_new = False
        for i in range(count):
            cells = rows.nth(i).locator("[role=gridcell]")
            cc = cells.count()
            if cc < 4:
                continue
            texts = [_clean(cells.nth(j).inner_text()) for j in range(cc)]
            artg_id = texts[1] if len(texts) > 1 else ""
            if not artg_id.isdigit():
                continue
            if artg_id in seen:
                continue
            seen[artg_id] = {
                "artg_id": artg_id,
                "product_name": texts[2] if len(texts) > 2 else "",
                "sponsor_name": texts[3] if len(texts) > 3 else "",
                "manufacturer_name": texts[4] if len(texts) > 4 else "",
            }
            found_new = True
        if len(seen) >= max_rows:
            print(f"artg_search: hit max_rows cap ({max_rows}); date filter may not have applied. Stopping scroll.")
            break
        if not found_new:
            stable_rounds += 1
            if stable_rounds >= 3:
                break
        else:
            stable_rounds = 0
        try:
            grid.locator(".scrollDown").first.click(timeout=1000)
        except Exception:
            try:
                grid.hover()
                grid.page.mouse.wheel(0, 500)
            except Exception:
                break
    return list(seen.values())


def _matches_keyword(entry: dict[str, str], keywords: list[str]) -> str:
    text = f"{entry['product_name']} {entry['manufacturer_name']}".lower()
    for kw in keywords:
        if kw.lower() in text:
            return kw
    return ""


def _matches_competitor(entry: dict[str, str], competitor_names: list[str]) -> str:
    sponsor = entry["sponsor_name"].lower()
    for name in competitor_names:
        if name.lower() in sponsor:
            return name
    return ""


def load_previous_ids() -> set[str]:
    if not ARTG_IDS_SNAPSHOT.exists():
        return set()
    try:
        data = json.loads(ARTG_IDS_SNAPSHOT.read_text(encoding="utf-8"))
        return set(data.get("artg_ids", []))
    except Exception:  # noqa: BLE001
        return set()


def save_ids(all_ids: set[str]) -> None:
    ARTG_IDS_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    ARTG_IDS_SNAPSHOT.write_text(
        json.dumps({"artg_ids": sorted(all_ids)}, indent=2), encoding="utf-8"
    )


def find_new_artg_listings(
    keywords: list[str],
    competitor_names: list[str],
    lookback_days: int = 21,
) -> tuple[list[dict[str, str]], list[str]]:
    """Returns (relevant_new_entries, warnings). Also updates the ARTG ID
    snapshot on disk as a side effect so the next run can diff against it."""
    warnings: list[str] = []
    previous_ids = load_previous_ids()
    first_run = not previous_ids and not ARTG_IDS_SNAPSHOT.exists()

    rows: list[dict[str, str]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            frame = _open_advanced_search(page)
            if frame is None:
                warnings.append("Could not load the ARTG Power BI report frame.")
            else:
                end = datetime.now()
                start = end - timedelta(days=lookback_days)
                if not set_date_range(page, frame, start, end):
                    warnings.append(
                        "Could not set the ARTG date-range filter; falling back to "
                        "whatever the default results view shows (bounded scrape)."
                    )
                rows = extract_grid_rows(frame)
        finally:
            browser.close()

    if not rows:
        warnings.append("No rows scraped from the ARTG results grid this run.")

    all_ids_this_run = {r["artg_id"] for r in rows}
    save_ids(previous_ids | all_ids_this_run)

    relevant: list[dict[str, str]] = []
    for row in rows:
        kw = _matches_keyword(row, keywords)
        comp = _matches_competitor(row, competitor_names)
        if not kw and not comp:
            continue
        is_new = row["artg_id"] not in previous_ids
        if not is_new and not first_run:
            continue
        relevant.append(
            {
                **row,
                "matched_keyword": kw,
                "matched_competitor": comp,
            }
        )

    if first_run:
        warnings.append(
            "First ARTG scan: no prior snapshot to diff against, so all "
            "keyword/competitor matches in the lookback window are reported "
            "as a baseline rather than confirmed 'new since last scan'."
        )

    return relevant, warnings


if __name__ == "__main__":
    keywords = json.loads((ROOT / "config" / "artg_keywords.json").read_text())["keywords"]
    watchlist = json.loads((ROOT / "config" / "watchlist.json").read_text())
    competitor_names = [c["name"] for c in watchlist["competitors"]]
    found, warns = find_new_artg_listings(keywords, competitor_names)
    print(json.dumps({"found": found, "warnings": warns}, indent=2))
