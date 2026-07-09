"""One-off exploration script: the ARTG Search Visualisation Tool has an
"Advanced Search" page (linked from the home page) which is likely to have
real form inputs rather than the fragile Q&A search box we tried before.
Dump its structure and try running a search on it.

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


def dump(label: str, data) -> None:
    print(f"----{label}-JSON-START----")
    print(json.dumps(data, indent=2, default=str)[:20000])
    print(f"----{label}-JSON-END----")


def describe_elements(scope) -> list[dict]:
    return scope.eval_on_selector_all(
        "input, button, select, [role], textarea, a",
        """els => els.slice(0, 300).map(el => ({
            tag: el.tagName,
            type: el.getAttribute('type'),
            role: el.getAttribute('role'),
            placeholder: el.getAttribute('placeholder'),
            aria_label: el.getAttribute('aria-label'),
            id: el.id,
            name: el.getAttribute('name'),
            class: (el.className || '').toString().slice(0, 80),
            text: (el.innerText || '').slice(0, 60),
        }))""",
    )


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

        adv_link = pbi_frame.locator("[aria-label*='Advanced ARTG Search Page']").first
        try:
            adv_link.click(timeout=10000)
            print("Clicked Advanced Search nav link.")
        except Exception as exc:  # noqa: BLE001
            print(f"click advanced search failed: {exc}")
            browser.close()
            return

        page.wait_for_timeout(4000)

        adv_elements = describe_elements(pbi_frame)
        dump("ADV-ELEMENTS", adv_elements)

        try:
            grid_text = pbi_frame.locator("[role=grid]").first.inner_text(timeout=5000)
        except Exception as exc:  # noqa: BLE001
            grid_text = f"<grid read error: {exc}>"
        print("ADV PAGE GRID TEXT:")
        print(grid_text[:3000])

        page.screenshot(path=str(OUT / "03_advanced_search.png"), full_page=True)

        browser.close()

    print(f"Wrote debug output to {OUT}")


if __name__ == "__main__":
    main()
