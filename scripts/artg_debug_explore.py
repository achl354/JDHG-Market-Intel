"""One-off exploration script: the Advanced Search page has a "Goods Started
by Date Range" visual backed by two `.date-slicer-input` text fields. Try
setting those to a recent date range and see if the results grid actually
filters to newly-started ARTG entries.

Not part of the regular scan pipeline. Run via the artg-debug-explore workflow
because compliance.health.gov.au is not reachable from most sandboxes.
Artifact download is also blocked from the dev sandbox, so everything of
interest is printed to stdout (the job log) rather than relying solely on the
uploaded artifact.
"""
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "artg_debug_output"
URL = "https://compliance.health.gov.au/artg/"
START_DATE = "01 July 2026"
END_DATE = "10 July 2026"


def grid_summary(frame) -> str:
    try:
        grid = frame.locator("[role=grid]").first
        rows = grid.locator("[role=row]")
        count = rows.count()
        sample = []
        for i in range(min(count, 8)):
            cells = rows.nth(i).locator("[role=gridcell]")
            cc = cells.count()
            sample.append([cells.nth(j).inner_text().strip()[:40] for j in range(cc)])
        return f"row_count={count} sample={json.dumps(sample)}"
    except Exception as exc:  # noqa: BLE001
        return f"<grid read error: {exc}>"


def main() -> None:
    OUT.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        print(f"Navigating to {URL}")
        page.goto(URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(4000)

        pbi_frame = next((f for f in page.frames if "powerbi.com" in f.url), None)
        if pbi_frame is None:
            print("No Power BI frame found, aborting.")
            browser.close()
            return

        pbi_frame.locator("[aria-label*='Advanced ARTG Search Page']").first.click(timeout=10000)
        page.wait_for_timeout(4000)
        print("BEFORE:", grid_summary(pbi_frame))

        date_inputs = pbi_frame.locator(".date-slicer-input")
        n = date_inputs.count()
        print(f"date-slicer-input count: {n}")
        for i in range(n):
            try:
                html = date_inputs.nth(i).evaluate("e => e.outerHTML.slice(0,300)")
                print(f"  date input #{i}: {html}")
            except Exception as exc:  # noqa: BLE001
                print(f"  date input #{i} evaluate failed: {exc}")

        if n >= 2:
            for i, value in [(0, START_DATE), (1, END_DATE)]:
                try:
                    el = date_inputs.nth(i)
                    el.click(timeout=3000)
                    el.fill("", timeout=2000)
                    el.type(value, delay=60)
                    el.press("Enter")
                    print(f"Set date input #{i} to {value!r}")
                except Exception as exc:  # noqa: BLE001
                    print(f"  failed to set date input #{i}: {exc}")
            page.wait_for_timeout(5000)
            print("AFTER DATE FILTER:", grid_summary(pbi_frame))
            page.wait_for_timeout(4000)
            print("AFTER EXTRA WAIT:", grid_summary(pbi_frame))
        else:
            print("Fewer than 2 date-slicer-input elements found; cannot set range.")

        page.screenshot(path=str(OUT / "05_date_filter.png"), full_page=True)
        browser.close()

    print(f"Wrote debug output to {OUT}")


if __name__ == "__main__":
    main()
