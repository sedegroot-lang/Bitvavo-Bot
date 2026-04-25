"""Capture screenshots of every Dashboard V2 tab via Playwright."""
from __future__ import annotations
import sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5002/"
OUT = Path(__file__).resolve().parent.parent / "_screenshots_dashboard"
OUT.mkdir(exist_ok=True)

TABS = ["overview", "trades", "ai", "memory", "shadow", "roadmap", "parameters", "grid", "hodl", "markets"]


def main() -> int:
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        page = ctx.new_page()
        page.on("pageerror", lambda e: print(f"[JS ERROR] {e}"))
        page.on("console", lambda msg: print(f"[CONSOLE {msg.type}] {msg.text}") if msg.type in ("error", "warning") else None)

        page.goto(BASE, wait_until="networkidle", timeout=20000)
        page.wait_for_timeout(2000)  # let charts render

        for tab in TABS:
            page.evaluate(f"() => {{ const root = document.querySelector('body'); const a = Alpine.$data(root); a.tab = '{tab}'; if (a.tab === 'markets') a.loadMarkets(); }}")
            page.wait_for_timeout(900)
            out = OUT / f"{tab}.png"
            page.screenshot(path=str(out), full_page=True)
            print(f"  OK {tab}.png ({out.stat().st_size // 1024} KB)")

        # Mobile - capture each tab at iPhone-12 viewport (390x844)
        ctx_m = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
        m = ctx_m.new_page()
        m.on("pageerror", lambda e: print(f"[MOBILE JS ERROR] {e}"))
        m.goto(BASE, wait_until="networkidle", timeout=20000)
        m.wait_for_timeout(2000)
        for tab in TABS:
            m.evaluate(f"() => {{ const root = document.querySelector('body'); const a = Alpine.$data(root); a.tab = '{tab}'; if (a.tab === 'markets') a.loadMarkets(); }}")
            m.wait_for_timeout(900)
            out = OUT / f"mobile_{tab}.png"
            m.screenshot(path=str(out), full_page=True)
            print(f"  OK mobile_{tab}.png ({out.stat().st_size // 1024} KB)")

        b.close()
    print(f"\nDone — saved to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
