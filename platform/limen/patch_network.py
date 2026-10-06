#!/usr/bin/env python3
"""Pilot patch for musegadget's network.py: report a fixed SSID from env.

On a wired-only host there is no real Wi-Fi SSID to report, and the Muse
Android app may refuse to send provision_v2 for the placeholder entry
("Use current connection") — see upstream issue #79. The reported SSID is
only used by the app to match the phone's current network; the gadget
ignores Wi-Fi credentials on this path anyway.

Set MUSEGADGET_REPORT_SSID in the container env to enable the override.
Fails the build loudly if upstream changes the expected line.
"""

import glob
import sys

PATHS = glob.glob(
    "/opt/musegadget/venv/lib/python3.*/site-packages/musegadget/network.py",
)
if len(PATHS) != 1:
    sys.exit(f"network.py not found uniquely: {PATHS}")
PATH = PATHS[0]
with open(PATH, encoding="utf-8") as handle:
    text = handle.read()

NEEDLE = '"ssid": active_wifi_ssid() or CURRENT_CONNECTION_LABEL,'
REPLACEMENT = NEEDLE.replace(
    "active_wifi_ssid()",
    'os.environ.get("MUSEGADGET_REPORT_SSID") or active_wifi_ssid()',
)
if NEEDLE not in text:
    sys.exit("expected ssid line not found; upstream changed, patch needs review")
text = text.replace(NEEDLE, REPLACEMENT)
if "\nimport os\n" not in text:
    text = text.replace("\nimport re\n", "\nimport os\nimport re\n", 1)
with open(PATH, "w", encoding="utf-8") as handle:
    handle.write(text)
print(f"patched {PATH}")
