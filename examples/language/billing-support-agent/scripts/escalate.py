#!/usr/bin/env python3
"""Open a tier-2 ticket for an angry billing customer.

stdin:  {"state": {"message": str, "tone": str}, "assets": {"config": str}, "expects": {...}}
stdout: {"ticket_id": int, "queue": str}
"""
import hashlib
import json
import sys

payload = json.load(sys.stdin)
state = payload["state"]
config = json.loads(payload["assets"]["config"])

ticket_id = int(hashlib.sha256(state["message"].encode("utf-8")).hexdigest(), 16) % 100_000
json.dump({"ticket_id": ticket_id, "queue": config["queue"]}, sys.stdout)
