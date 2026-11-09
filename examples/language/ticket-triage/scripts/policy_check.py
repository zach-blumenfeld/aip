"""Does the reply quote the policy correctly? A stub: a script that drives a route or a loop
produces an answer type, and its answer is `{"value": ...}` alone, with no confidence (spec 2.4).
This one passes when the policy's first sentence appears in the reply."""

import json
import sys

payload = json.load(sys.stdin)
state = payload["state"]
first_sentence = state["policy"].split(".")[0].strip()
json.dump({"passed": {"value": bool(first_sentence) and first_sentence in state["reply"]}}, sys.stdout)
