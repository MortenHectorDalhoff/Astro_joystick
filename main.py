#!/usr/bin/env python3
"""Entry point for the joystick-driven ASCOM telescope controller."""

from __future__ import annotations

import argparse
import sys
import tkinter as tk

from astro_joystick import TelescopeJoystickApp


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Joystick telescope controller")
    parser.add_argument("--screenshot", metavar="PATH", help="Save a UI screenshot to PATH and exit.")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    root = tk.Tk()
    app = TelescopeJoystickApp(root)

    if args.screenshot:
        def capture_and_exit() -> None:
            try:
                app.save_screenshot(args.screenshot)
                print(f"Saved screenshot to {args.screenshot}")
            except Exception as exc:  # pragma: no cover - environment dependent
                print(f"Unable to save screenshot: {exc}", file=sys.stderr)
            finally:
                root.destroy()

        root.after(1200, capture_and_exit)
        root.mainloop()
        return 0

    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
