#!/usr/bin/env python3
"""Generate the four required secrets for a production .env file.

    python generate_secrets.py

Copy the printed lines into your .env (or run:  python generate_secrets.py >> .env).
Keep these secret. If you lose ENCRYPTION_KEY you cannot decrypt stored data.
"""
import secrets

print("# --- generated secrets (keep private) ---")
for name in ("SECRET_KEY", "JWT_SECRET_KEY", "ENCRYPTION_KEY"):
    print(f"{name}={secrets.token_hex(32)}")
# A strong default DB password suggestion (you may replace it):
print(f"DB_PASSWORD={secrets.token_urlsafe(24)}")
