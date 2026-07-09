"""One-off exploration script: verify that typing into the "Focussed Search"
box on the ARTG Advanced Search page actually filters the results grid, and
capture the query network traffic while doing it.

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
SEARCH_TERM = "Haines"


def dump(label: str, data) -> None:
    print(f"----{label}-JSON-START----")
    print(json.dumps(data, indent=2, default=str)[:20000])
    print(f"----{label}-JSON-END----")


def grid_summary(frame) -> str:
    try:
        grid = frame.locator("[role=grid]").first
        rows = grid.locator("[role=row]")
        count = rows.count()
        sample = []
        for i in range(min(count, 6)):
            cells = rows.nth(i).locator("[role=gridcell]")
            cc = cells.count()
            sample.append([cells.nth(j).inner_text().strip()[:40] for j in range(cc)])
        return f"row_count={count} sample={json.dumps(sample)}"
    except Exception as exc:  # noqa: BLE001
        return f"<grid read error: {exc}>"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    network_log: list[dict] = []

    def on_response(response):
        req = response.request
        if req.resource_type in ("xhr", "fetch") and "analysis.windows.net" in response.url and "querydata" in response.url.lower():
            entry = {"url": response.url, "status": response.status}
            try:
                entry["body_snippet"] = response.text()[:4000]
            except Exception as exc:  # noqa: BLE001
                entry["body_error"] = str(exc)
            network_log.append(entry)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("response", on_response)

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
        print("On Advanced Search page.")
        print("BEFORE:", grid_summary(pbi_frame))

        focussed = pbi_frame.locator("text=Focussed Search").first
        try:
            focussed.click(timeout=10000)
            print("Clicked Focussed Search group.")
        except Exception as exc:  # noqa: BLE001
            print(f"click Focussed Search failed: {exc}")

        page.wait_for_timeout(1500)

        revealed = pbi_frame.locator("input, textarea, [contenteditable='true']")
        count = revealed.count()
        print(f"revealed input-like elements: {count}")
        typed = False
        for i in range(count):
            el = revealed.nth(i)
            try:
                if el.is_visible():
                    html = el.evaluate("e => e.outerHTML.slice(0,200)")
                    print(f"  candidate #{i}: {html}")
            except Exception:
                pass
        for i in range(count):
            el = revealed.nth(i)
            try:
                if el.is_visible():
                    el.click(timeout=2000)
                    el.type(SEARCH_TERM, delay=80)
                    typed = True
                    print(f"Typed into input #{i}")
                    break
            except Exception as exc:  # noqa: BLE001
                print(f"  input #{i} failed: {exc}")

        if not typed:
            print("Falling back to raw keyboard typing.")
            page.keyboard.type(SEARCH_TERM, delay=80)

        page.wait_for_timeout(3000)
        print("AFTER TYPE (before Enter):", grid_summary(pbi_frame))

        page.keyboard.press("Enter")
        page.wait_for_timeout(6000)
        print("AFTER ENTER:", grid_summary(pbi_frame))

        page.wait_for_timeout(4000)
        print("AFTER EXTRA WAIT:", grid_summary(pbi_frame))

        dump("QUERYDATA-CALLS", network_log)

        page.screenshot(path=str(OUT / "04_focussed_search.png"), full_page=True)
        browser.close()

    print(f"Wrote debug output to {OUT}")


if __name__ == "__main__":
    main()
