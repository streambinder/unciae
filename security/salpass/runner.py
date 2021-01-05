#!/bin/env python3

import argparse
import getpass
import hashlib
import os
import re
import sys

parser = argparse.ArgumentParser()
parser.add_argument("-s", "--short", help="Short version", action="store_true")
parser.add_argument("-v", "--version", help="Password version", type=int, default=1)
args = parser.parse_args()

payload = input("Payload: ").strip().lower()
salt = getpass.getpass("Salt: ")
salt_verify = ""
salt_verify_attempts = 0

while salt_verify != salt:
    salt_verify_attempts += 1
    if salt_verify_attempts > 3:
        print("Too many salt verification attempts. Exiting.")
        sys.exit(1)
    salt_verify = getpass.getpass("Retype salt (verification): ")

if re.match("^([a-z0-9-]+.)+[a-z]+$", payload) is None:
    print("Invalid payload {}".format(payload))
    sys.exit(1)

password_plain = "{}@{}{}".format(payload, salt, str("+") * (args.version - 1))
password_hash = hashlib.sha256(password_plain.encode("utf-8")).hexdigest()
password_nocase = password_hash[0:15] if not args.short else password_hash[0:7]
password_uncased = True
password = "#"

for char in password_nocase:
    if password_uncased and char.isalpha():
        password_uncased = False
        char = char.upper()
    password += char

print(
    "Password ({}, {}) is: {}".format(
        "short" if args.short else "standard", "v{}".format(args.version), password
    )
)