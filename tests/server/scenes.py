"""A store with something in every corner, for the tests that read it back: three procedures
published, one run as a draft, and one run of each kind the record distinguishes.

    fired     billing_support by name; the model is unsure of the tone (0.6), the route's check fires, a ticket is opened
    calm      billing_support by name; the model is sure, the agent drafts the reply
    agent     billing_support_agent by name; the agent classifies, its answer steers the route
    policy    fixed-policy from its folder (a draft); the aggregate fails once, the agent fixes, the loop exits on `Until`
    capped    fixed-policy again; the model never passes it, the loop hits its cap and the run fails
    batched   dynamic_policy by name; three policies checked in one model call per pass, one fails until fixed
"""

from __future__ import annotations

from pathlib import Path

import aip
from aip.client.server import Server
from aip.compiler import example_dir
from served import BillingModel, Model

CALM = "I was charged twice for March. Could you check?"
POLICIES = ["be polite", "be short", "use no names"]
PUBLISHED = ("billing-support", "billing-support-agent", "dynamic-policy")


def client(served, model=None, token: str | None = "secret", agent: str = "tests") -> aip.Client:
    return aip.Client(Server("http://testserver", token=token, session=served), decision_client=model, agent=agent)


def record(served, workdir: Path) -> dict[str, str]:
    """Publish and run; the run id of each scene by its name."""
    ids: dict[str, str] = {}
    for name in PUBLISHED:
        client(served).publish(example_dir(name))

    done = client(served, BillingModel(0.6), agent="claude").run("billing_support", {"message": CALM}, workdir=workdir, session="s1")
    ids["fired"] = done.run_id

    paused = client(served, BillingModel(0.95), agent="claude").run("billing_support", {"message": CALM}, workdir=workdir, session="s1")
    ids["calm"] = client(served, agent="claude").resume(paused, {"reply": "Refunded within 5 business days."}).run_id

    c = client(served, agent="codex")
    paused = c.run("billing_support_agent", {"message": CALM}, workdir=workdir, session="s2")
    ids["agent"] = c.resume(paused, {"billing": True, "tone": "angry"}).run_id

    c = client(served, Model(lambda state, _: 0.9 if state["work"].endswith("!") else 0.6), agent="codex")
    paused = c.run(example_dir("fixed-policy"), {"request": "a welcome note"}, workdir=workdir, session="s2")
    paused = c.resume(paused, {"work": "Welcome"})
    ids["policy"] = c.resume(paused, {"work": "Welcome!"}).run_id

    c = client(served, Model(0.3), agent="codex")
    paused = c.run(example_dir("fixed-policy"), {"request": "a welcome note"}, workdir=workdir)
    try:
        for _ in range(4):
            paused = c.resume(paused, {"work": "Welcome"})
    except aip.RunError as failed:
        assert failed.kind == "loop_cap", failed
        ids["capped"] = failed.run_id

    model = Model(lambda state, instruction: 0.2 if "short" in instruction and "fixed" not in state["work"] else 0.95)
    c = client(served, model, token="runner", agent="tests")
    paused = c.run("dynamic_policy", {"task": "write a note", "policies": POLICIES}, workdir=workdir)
    paused = c.resume(paused, {"work": "a draft"})
    ids["batched"] = c.resume(paused, {"work": "a fixed draft"}).run_id
    assert set(ids) == {"fired", "calm", "agent", "policy", "capped", "batched"}, ids
    return ids
