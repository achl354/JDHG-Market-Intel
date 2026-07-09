"""One-off exploration script: dump the DOM, interactive elements, and network
traffic of the TGA ARTG Search Visualisation Tool so we can learn its selectors
and (ideally) find a JSON API to call directly instead of scraping HTML.

Not part of the regular scan pipeline. Run via the artg-debug-explore workflow
because compliance.health.gov.au is not reachable from most sandboxes.
"""
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "artg_debug_output"
URL = "https://compliance.health.gov.au/artg/"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    network_log: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        def on_response(response):
            req = response.request
            if req.resource_type in ("xhr", "fetch"):
                entry = {
                    "url": response.url,
                    "method": req.method,
                    "status": response.status,
                    "resource_type": req.resource_type,
                }
                try:
                    ctype = response.headers.get("content-type", "")
                    if "json" in ctype:
                        text = response.text()
                        entry["body_snippet"] = text[:4000]
                except Exception as exc:  # noqa: BLE001
                    entry["body_error"] = str(exc)
                network_log.append(entry)

        page.on("response", on_response)

        print(f"Navigating to {URL}")
        page.goto(URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3000)

        page.screenshot(path=str(OUT / "01_initial_load.png"), full_page=True)
        (OUT / "01_initial_load.html").write_text(page.content(), encoding="utf-8")

        elements = page.eval_on_selector_all(
            "input, button, select, [role=button], [role=searchbox], iframe",
            """els => els.map(el => ({
                tag: el.tagName,
                type: el.getAttribute('type'),
                role: el.getAttribute('role'),
                placeholder: el.getAttribute('placeholder'),
                aria_label: el.getAttribute('aria-label'),
                id: el.id,
                name: el.getAttribute('name'),
                class: el.className,
                text: (el.innerText || '').slice(0, 80),
                src: el.getAttribute('src'),
            }))""",
        )
        (OUT / "01_interactive_elements.json").write_text(
            json.dumps(elements, indent=2), encoding="utf-8"
        )

        frames_info = [{"url": f.url, "name": f.name} for f in page.frames]
        (OUT / "01_frames.json").write_text(json.dumps(frames_info, indent=2), encoding="utf-8")

        (OUT / "01_network_after_load.json").write_text(
            json.dumps(network_log, indent=2), encoding="utf-8"
        )

        print(f"Found {len(elements)} interactive elements, {len(frames_info)} frames, "
              f"{len(network_log)} xhr/fetch responses.")
        for f in frames_info:
            print(f"  frame: {f}")

        browser.close()

    print(f"Wrote debug output to {OUT}")


if __name__ == "__main__":
    main()
