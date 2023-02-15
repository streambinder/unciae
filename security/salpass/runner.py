#!/usr/bin/env python3

import argparse
import getpass
import hashlib
import re
import sys

parser = argparse.ArgumentParser()
parser.add_argument("payload", nargs="?")
parser.add_argument("-s", "--short", help="Short version", action="store_true")
parser.add_argument("-v", "--version", help="Password version", type=int, default=1)
parser.add_argument(
    "-c", "--clip", help="Copy to clipboard only", action="store_true", default=False
)
args = parser.parse_args()

if not args.payload:
    parser.print_help()
    sys.exit(1)

if not re.match("^([a-z0-9-]+.)+[a-z]+$", args.payload):
    print("Invalid payload {}".format(args.payload))
    sys.exit(1)

salt = None
if sys.stdin.isatty():
    salt = sys.stdin.readline().rstrip()
if not salt:
    salt = getpass.getpass("Salt: ")
    salt_verify = getpass.getpass("Verify: ")
    if salt != salt_verify:
        salt_last = getpass.getpass("Verify: ")
        if salt_last not in [salt, salt_verify]:
            print("Too many salt verification attempts. Exiting.")
            sys.exit(1)
        elif salt_last == salt_verify:
            salt = salt_last


password_plain = f"{args.payload}@{salt}{str('+') * (args.version - 1)}"
password_hash = hashlib.sha256(password_plain.encode("utf-8")).hexdigest()
password_nocase = password_hash[0:15] if not args.short else password_hash[0:7]
password_uncased = True
password = "#"

for char in password_nocase:
    if password_uncased and char.isalpha():
        password_uncased = False
        char = char.upper()
    password += char

if args.clip:
    import pyperclip

    pyperclip.copy(password)
else:
    print(
        f"Password ({'short' if args.short else 'standard'}, v{args.version}) is: {password}"
    )
