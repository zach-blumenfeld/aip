"""Open a ticket in the tier-2 queue. A stub: it reads the state the runtime hands it on stdin
(`state` holds the step's Read keys) and writes the step's Produce keys as JSON on stdout."""

import json
import sys

payload = json.load(sys.stdin)
ticket = payload["state"]["ticket"]
json.dump({"reply": f"Your request has been escalated to our tier-2 team: {ticket}", "queue": "tier-2"}, sys.stdout)
