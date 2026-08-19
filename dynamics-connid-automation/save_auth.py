#!/usr/bin/env python3
"""Sign in to Dynamics 365 and SharePoint once, and save the session.

Opens a real browser window, walks you through the normal Microsoft sign-in
(including MFA), and then writes Playwright's ``storage_state`` — cookies plus
local storage — to the path in ``PLAYWRIGHT_STORAGE_STATE``. ``automate.py``
reuses that file, so no credentials ever appear in source or in the environment.

    python save_auth.py                 # sign in to both hosts and save
    python save_auth.py --output x.json # write somewhere else

The generated file grants access to your Microsoft account for as long as the
tokens inside it stay valid. Keep it out of version control and off shared
drives; re-run this script whenever automate.py reports an expired session.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import stat
import sys
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import Error as PlaywrightError, Page, async_playwright

DEFAULT_STORAGE_STATE = "auth_state.json"
SIGN_IN_TIMEOUT_MS = 300_000  # five minutes of human time per site


async def prompt(message: str) -> None:
    """Wait for Enter without blocking the asyncio loop."""
    await asyncio.get_running_loop().run_in_executor(None, input, message)


async def visit(page: Page, url: str, label: str) -> None:
    print(f"\n→ Opening {label}: {url[:110]}")
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=SIGN_IN_TIMEOUT_MS)
    except PlaywrightError as exc:
        print(f"  ! Navigation reported: {exc}")
        print("    Continue in the browser window if the page still loaded.")
    await prompt(
        f"  Sign in to {label} in the browser window, wait until it has fully "
        "loaded, then press Enter here… "
    )


async def save_auth(
    output: Path, dynamics_url: str, excel_url: str, executable_path: str | None = None
) -> int:
    async with async_playwright() as playwright:
        launch_args: dict[str, object] = {"headless": False}
        if executable_path:
            launch_args["executable_path"] = executable_path
        browser = await playwright.chromium.launch(**launch_args)
        context = await browser.new_context(viewport={"width": 1600, "height": 1000})
        page = await context.new_page()

        print("=" * 72)
        print("A browser window is open. Complete the Microsoft sign-in for BOTH")
        print("sites below — Dynamics and SharePoint issue separate cookies, and")
        print("automate.py needs both.")
        print("=" * 72)

        await visit(page, dynamics_url, "Dynamics 365")
        await visit(page, excel_url, "SharePoint (ADHOC.xlsx)")

        output.parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(output))
        await context.close()
        await browser.close()

    try:  # owner-only permissions; best effort on filesystems that support it
        os.chmod(output, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass

    print(f"\n✔ Saved the authenticated session to: {output.resolve()}")
    print("  Treat this file like a password. It is gitignored by default.")
    print("  Point PLAYWRIGHT_STORAGE_STATE at it in your .env, then run:")
    print("      python automate.py <case_url> --dry-run")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output",
        help="where to write the session file "
        "(default: PLAYWRIGHT_STORAGE_STATE, else auth_state.json)",
    )
    parser.add_argument("--dynamics-url", help="override DYNAMICS_LOGIN_URL")
    parser.add_argument("--excel-url", help="override EXCEL_WORKBOOK_URL")
    args = parser.parse_args(argv)

    load_dotenv()
    output = Path(
        args.output or os.getenv("PLAYWRIGHT_STORAGE_STATE") or DEFAULT_STORAGE_STATE
    )
    dynamics_url = (
        args.dynamics_url
        or os.getenv("DYNAMICS_LOGIN_URL")
        or os.getenv("DYNAMICS_CASE_URL", "")
    )
    excel_url = args.excel_url or os.getenv("EXCEL_WORKBOOK_URL", "")

    missing = [
        name
        for name, value in (
            ("DYNAMICS_LOGIN_URL (or DYNAMICS_CASE_URL)", dynamics_url),
            ("EXCEL_WORKBOOK_URL", excel_url),
        )
        if not value
    ]
    if missing:
        print(
            "Missing configuration: "
            + ", ".join(missing)
            + "\nCopy .env.example to .env and fill it in (see README.md).",
            file=sys.stderr,
        )
        return 1

    if output.exists():
        answer = input(f"{output} already exists. Overwrite? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Aborted; the existing session file was left untouched.")
            return 0

    return asyncio.run(
        save_auth(
            output,
            dynamics_url,
            excel_url,
            os.getenv("PLAYWRIGHT_EXECUTABLE_PATH") or None,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
