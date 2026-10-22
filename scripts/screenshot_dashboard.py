"""Screenshot the dashboard tabs (report figures + visual check).

    python scripts/screenshot_dashboard.py [--run test_s4] [--trace <id>]
"""
import argparse
import time

from playwright.sync_api import sync_playwright

from logpulse.paths import FIGURES


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8501")
    ap.add_argument("--run", default=None, help="replay this recorded run instead of live")
    ap.add_argument("--tabs", nargs="+", default=["Live", "Investigate", "Normal flow graph", "Template library",
                                                   "Incidents", "Benchmarks"])
    ap.add_argument("--react", action="store_true", help="also capture the React page on :9000/ui")
    a = ap.parse_args()
    FIGURES.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=1)
        pg.goto(a.url)
        pg.wait_for_selector("text=LogPulse", timeout=60000)
        time.sleep(6)
        if a.run:
            pg.get_by_test_id("stSidebar").get_by_role("combobox").first.click()
            pg.get_by_role("option", name=a.run).click()
            time.sleep(8)
        for tab in a.tabs:
            pg.get_by_role("tab", name=tab).click()
            time.sleep(8)
            name = {"Live": "live", "Investigate": "investigate", "Normal flow graph": "flowgraph",
                    "Template library": "templates", "Incidents": "incidents", "Benchmarks": "benchmarks"}[tab]
            pg.screenshot(path=str(FIGURES / f"fig_dashboard_{name}.png"), full_page=True)
            print("saved", name)
        if a.react:
            for view in ("topology", "flow graph"):
                pg.goto("http://localhost:9000/ui")
                time.sleep(4)
                pg.get_by_role("button", name=view).click()
                time.sleep(4)
                pg.screenshot(path=str(FIGURES / f"fig_react_{view.replace(' ', '')}.png"))
                print("saved react", view)
        b.close()


if __name__ == "__main__":
    main()
