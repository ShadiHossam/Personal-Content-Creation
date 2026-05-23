"""Open the persistent scraper Chromium so you can log into social accounts.

Run with:  python open_login_browser.py

A Chromium window will open with tabs for LinkedIn, X (Twitter), and Instagram.
Log into each one, then close the window. Sessions are saved to the persistent
profile and will be reused by the scraper automatically.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pathlib import Path
from backend.scraper_tool.extension_driver import _ensure_profile, settings

def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    profile_dir = _ensure_profile()
    ext_dir = Path(settings.extension_dir) / "instant-data-scraper"
    exe = settings.chromium_executable_path or None

    # Build args — load extension only if it exists
    args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if ext_dir.exists():
        args += [
            f"--disable-extensions-except={ext_dir}",
            f"--load-extension={ext_dir}",
        ]

    print("Opening browser… Log in to each tab, then close the window.")
    print(f"Profile saved at: {profile_dir}")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            executable_path=exe or None,
            headless=False,
            args=args,
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        )

        # Stealth — hide webdriver from every page including Google OAuth
        ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            if (!window.chrome) window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        """)

        pages_to_open = [
            ("LinkedIn",  "https://www.linkedin.com/login"),
            ("X/Twitter", "https://x.com/login"),
            ("Instagram", "https://www.instagram.com/accounts/login/"),
        ]

        # Reuse the first tab, open new tabs for the rest
        first_page = ctx.pages[0] if ctx.pages else ctx.new_page()
        first_page.goto(pages_to_open[0][1], wait_until="domcontentloaded")

        for name, url in pages_to_open[1:]:
            tab = ctx.new_page()
            tab.goto(url, wait_until="domcontentloaded")

        print("Browser open. Close it when you're done logging in.")
        # Wait indefinitely until the user closes the window (up to 30 min)
        try:
            ctx.wait_for_event("close", timeout=1_800_000)
        except Exception:
            pass
        print("Browser closed. Sessions saved.")


if __name__ == "__main__":
    main()
