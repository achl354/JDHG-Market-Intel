"""One-off exploration script: figure out how to type a search term into the
TGA ARTG Search Visualisation Tool (a Power BI report embed) and read back
the results grid, so we can build a real scraper.

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


def grid_text(frame) -> str:
    try:
        return frame.locator("[role=grid]").first.inner_text(timeout=5000)
    except Exception as exc:  # noqa: BLE001
        return f"<grid read error: {exc}>"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    network_log: list[dict] = []
    interesting_hosts = ("analysis.windows.net", "powerbi.com/explore", "querydata")

    def on_request(request):
        if request.resource_type in ("xhr", "fetch") and "analysis.windows.net" in request.url:
            entry = {
                "phase": "request",
                "url": request.url,
                "method": request.method,
                "headers": dict(request.headers),
            }
            try:
                entry["post_data"] = (request.post_data or "")[:6000]
            except Exception as exc:  # noqa: BLE001
                entry["post_data_error"] = str(exc)
            network_log.append(entry)

    def on_response(response):
        req = response.request
        if req.resource_type in ("xhr", "fetch") and "analysis.windows.net" in response.url:
            entry = {"phase": "response", "url": response.url, "status": response.status}
            try:
                entry["body_snippet"] = response.text()[:6000]
            except Exception as exc:  # noqa: BLE001
                entry["body_error"] = str(exc)
            network_log.append(entry)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("request", on_request)
        page.on("response", on_response)

        print(f"Navigating to {URL}")
        page.goto(URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(4000)

        pbi_frame = next((f for f in page.frames if "powerbi.com" in f.url), None)
        if pbi_frame is None:
            print("No Power BI frame found, aborting.")
            browser.close()
            return

        print("BEFORE SEARCH:")
        print(grid_text(pbi_frame)[:3000])

        search_group = pbi_frame.locator("[aria-label^='Search by AUST L']").first
        try:
            search_group.click(timeout=10000)
            print("Clicked search group.")
        except Exception as exc:  # noqa: BLE001
            print(f"click search group failed: {exc}")

        page.wait_for_timeout(1500)

        revealed = pbi_frame.locator("input, textarea, [contenteditable='true']")
        count = revealed.count()
        print(f"revealed input-like elements: {count}")
        revealed_info = []
        for i in range(min(count, 15)):
            el = revealed.nth(i)
            try:
                html = el.evaluate("el => el.outerHTML.slice(0, 300)")
            except Exception as exc:  # noqa: BLE001
                html = f"<error: {exc}>"
            try:
                visible = el.is_visible()
            except Exception:
                visible = None
            revealed_info.append({"i": i, "html": html, "visible": visible})
        dump("REVEALED-INPUTS", revealed_info)

        typed = False
        for i in range(min(count, 15)):
            el = revealed.nth(i)
            try:
                if el.is_visible():
                    el.click(timeout=2000)
                    el.type(SEARCH_TERM, delay=60)
                    typed = True
                    print(f"Typed into revealed input #{i}")
                    break
            except Exception as exc:  # noqa: BLE001
                print(f"  input #{i} failed: {exc}")

        if not typed:
            print("No revealed input accepted typing; trying raw keyboard input instead.")
            page.keyboard.type(SEARCH_TERM, delay=60)

        page.wait_for_timeout(1500)
        page.keyboard.press("Enter")
        page.wait_for_timeout(5000)

        print("AFTER SEARCH:")
        print(grid_text(pbi_frame)[:5000])

        dump("NETWORK-QUERY-CALLS", network_log)

        page.screenshot(path=str(OUT / "02_after_search.png"), full_page=True)

        browser.close()

    print(f"Wrote debug output to {OUT}")


if __name__ == "__main__":
    main()
