"""One-off exploration script: dump the DOM, interactive elements, and network
traffic of the TGA ARTG Search Visualisation Tool so we can learn its selectors
and (ideally) find a JSON API to call directly instead of scraping HTML.

The tool embeds a Power BI report (app.powerbi.com/reportEmbed) inside an
iframe, so this also drills into that frame and tries a keyword search.

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
        "input, button, select, [role], textarea",
        """els => els.slice(0, 200).map(el => ({
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
    network_log: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        def on_request(request):
            if request.resource_type in ("xhr", "fetch"):
                entry = {"phase": "request", "url": request.url, "method": request.method}
                try:
                    entry["post_data"] = (request.post_data or "")[:2000]
                except Exception as exc:  # noqa: BLE001
                    entry["post_data_error"] = str(exc)
                network_log.append(entry)

        def on_response(response):
            req = response.request
            if req.resource_type in ("xhr", "fetch"):
                entry = {"phase": "response", "url": response.url, "status": response.status}
                try:
                    entry["body_snippet"] = response.text()[:3000]
                except Exception as exc:  # noqa: BLE001
                    entry["body_error"] = str(exc)
                network_log.append(entry)

        page.on("request", on_request)
        page.on("response", on_response)

        print(f"Navigating to {URL}")
        page.goto(URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(4000)

        page.screenshot(path=str(OUT / "01_initial_load.png"), full_page=True)

        frames_info = [{"url": f.url, "name": f.name} for f in page.frames]
        dump("FRAMES", frames_info)

        main_elements = describe_elements(page)
        dump("MAIN-ELEMENTS", main_elements)

        pbi_frame = next((f for f in page.frames if "powerbi.com" in f.url), None)
        if pbi_frame is not None:
            print(f"Found Power BI frame: {pbi_frame.url}")
            try:
                pbi_frame.wait_for_load_state("networkidle", timeout=20000)
            except Exception as exc:  # noqa: BLE001
                print(f"pbi_frame wait_for_load_state error: {exc}")
            page.wait_for_timeout(4000)

            try:
                pbi_elements = describe_elements(pbi_frame)
            except Exception as exc:  # noqa: BLE001
                pbi_elements = [{"error": str(exc)}]
            dump("PBI-ELEMENTS", pbi_elements)

            # Power BI often nests another level of iframes for the report canvas.
            nested = [{"url": f.url, "name": f.name} for f in pbi_frame.child_frames]
            dump("PBI-CHILD-FRAMES", nested)
            for child in pbi_frame.child_frames:
                try:
                    child.wait_for_load_state("networkidle", timeout=15000)
                except Exception:  # noqa: BLE001
                    pass
                try:
                    child_elements = describe_elements(child)
                except Exception as exc:  # noqa: BLE001
                    child_elements = [{"error": str(exc)}]
                dump(f"PBI-CHILD-ELEMENTS-{child.url[:40]}", child_elements)
        else:
            print("No Power BI frame found.")

        dump("NETWORK-AFTER-LOAD", network_log)

        print(
            f"Found {len(main_elements)} main-page elements, {len(frames_info)} frames, "
            f"{len(network_log)} xhr/fetch entries."
        )

        browser.close()

    print(f"Wrote debug output to {OUT}")


if __name__ == "__main__":
    main()
