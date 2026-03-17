"""
Dashboard Screenshot Tool
Takes full-page screenshots of all dashboard pages and saves them to docs/screenshots/.
"""
import os
import sys
import time
from pathlib import Path

# Ensure script can be run from project root
PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = PROJECT_ROOT / "docs" / "screenshots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PAGES = [
    ("portfolio",      "http://localhost:5001/portfolio"),
    ("hodl",           "http://localhost:5001/hodl"),
    ("hedge",          "http://localhost:5001/hedge"),
    ("grid",           "http://localhost:5001/grid"),
    ("ai",             "http://localhost:5001/ai"),
    ("parameters",     "http://localhost:5001/parameters"),
    ("performance",    "http://localhost:5001/performance"),
    ("analytics",      "http://localhost:5001/analytics"),
    ("reports",        "http://localhost:5001/reports"),
    ("settings",       "http://localhost:5001/settings"),
    ("notifications",  "http://localhost:5001/notifications"),
]

def take_screenshots():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=1,
        )
        page = context.new_page()

        for name, url in PAGES:
            print(f"  → Capturing {name}...")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                # Wait for content to settle (charts, dynamic content)
                time.sleep(3)

                out_path = OUTPUT_DIR / f"{name}.png"
                page.screenshot(path=str(out_path), full_page=True, timeout=60000)
                file_size = out_path.stat().st_size // 1024
                print(f"    ✓ Saved {out_path.name} ({file_size}KB)")
            except Exception as e:
                print(f"    ✗ Failed {name}: {e}")

        context.close()
        browser.close()

    print(f"\nScreenshots saved to: {OUTPUT_DIR}")

if __name__ == "__main__":
    print("Taking dashboard screenshots...")
    take_screenshots()
