#!/usr/bin/env python3
"""Store an API key in the OS keychain (nothing is written to disk). Run in a terminal:
    python setkey.py            # Anthropic key (find clips, hooks)
    python setkey.py groq       # Groq key (free cloud transcription)"""
import getpass, sys

import keyring

KINDS = {"anthropic": ("Anthropic", "sk-ant-"), "groq": ("Groq", "gsk_")}
kind = (sys.argv[1] if len(sys.argv) > 1 else "anthropic").lower()
if kind not in KINDS:
    raise SystemExit(f"usage: python setkey.py [{'|'.join(KINDS)}]")
label, prefix = KINDS[kind]
k = getpass.getpass(f"{label} API key (input hidden): ").strip()
if not k.startswith(prefix):
    raise SystemExit(f"That doesn't look like a {label} key (should start with {prefix}). Nothing saved.")
keyring.set_password("memeclip", kind, k)
print(f"Saved the {label} key to your keychain.")
