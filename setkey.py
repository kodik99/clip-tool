#!/usr/bin/env python3
"""Store your Anthropic API key in the OS keychain (nothing is written to disk). Run in a terminal."""
import getpass, keyring
k = getpass.getpass("Anthropic API key (input hidden): ").strip()
if not k.startswith("sk-ant-"):
    raise SystemExit("That doesn't look like an Anthropic key (should start with sk-ant-). Nothing saved.")
keyring.set_password("memeclip", "anthropic", k)
print("Saved to your keychain.")
