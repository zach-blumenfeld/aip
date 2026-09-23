#!/usr/bin/env python3
"""Open a tier-2 ticket for an angry billing customer.

stdin:  {"currentState": {"message": str, "tone": str, ...}, "assets": {"config": str}, "expects": {...}}
stdout: {"message": str, "ticket_id": int, "queue": str}
"""
import json
import sys

payload = json.load(sys.stdin)
state = payload["currentState"]
config = json.loads(payload["assets"]["config"])

ticket_id = abs(hash(state["message"])) % 100_000
json.dump({"message": state["message"], "ticket_id": ticket_id, "queue": config["queue"]}, sys.stdout)
