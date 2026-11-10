"""The real server, in process, for the client's tests: `aip.server.app.create_app` over an
in-memory Relate store behind FastAPI's test client, standing in for an httpx session:
`Server(url, session=Served())`. Until S1 this was a fake speaking the client's contract; the
contract's own tests are `tests/server/test_contract.py`, which run the same app over both
backends.

`requests` lists every call made, and `runs[run_id]` is the server's record of a run, so a test
can say what the client sent and what the store kept. The catalog starts empty: the bundles the
package ships (`make_procedure`) are not published here unless a test asks (`builtins=True`), so
a test's catalog holds what the test published."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from aip.server.app import Token, create_app
from aip.server.backends.relate import RelateBackend

JSON = dict[str, Any]


class DownSession:
    """A session whose server is down: every request raises."""

    def request(self, method: str, path: str, **kwargs: Any):
        import httpx

        raise httpx.ConnectError(f"[Errno 61] Connection refused ({method} {path})")


class _Runs:
    def __init__(self, store):
        self.store = store

    def __getitem__(self, run_id: str) -> JSON:
        return self.store.run(run_id)


class Served:
    """`token_names` maps a bearer token to the user it stands for (every scope); `tokens` gives
    the `Token`s outright; with neither the server is open."""

    def __init__(self, backend: Any = None, token_names: dict[str, str] | None = None, tokens: dict[str, Token] | None = None,
                 **options: Any):
        self.backend = backend if backend is not None else RelateBackend(":memory:")
        self.store = self.backend.store
        tokens = {**{token: Token(name=name) for token, name in (token_names or {}).items()}, **(tokens or {})}
        options.setdefault("builtins", False)
        self.app = create_app(self.backend, tokens=tokens, **options)
        self.http = TestClient(self.app)
        self.requests: list[tuple[str, str]] = []
        self.runs = _Runs(self.store)

    def request(self, method: str, path: str, **kwargs: Any):
        self.requests.append((method, path))
        return self.http.request(method, path, **kwargs)

    def close(self) -> None:
        self.http.close()
        self.backend.close()


class Model:
    """Stands in for `TypeSafeClient` where every question is a `true_or_false`: each holds with
    probability `sure`, a number or a function of the state the step read and the question's
    own instruction (in a batch, each pass's copy of the question has its own)."""

    def __init__(self, sure: Any = 0.9, name: str = "jev-1"):
        self.sure, self.name = sure, name
        self.calls: list = []

    def system_one(self, state, questions, **_):
        self.calls.append((state, questions))
        answers = {name: {"type": "noul", "noul": self.sure(state["state"], q.instructions) if callable(self.sure) else self.sure}
                   for name, q in questions.items()}
        return {"model": self.name, "usage": {"input_tokens": 1, "output_tokens": 1}, "answers": answers}


class BillingModel:
    """Stands in for `TypeSafeClient` on `billing-support`: billing is clear (noul 0.97) and the
    tone is `calm` with probability `calm_p`."""

    def __init__(self, calm_p: float = 0.9, name: str = "jev-1"):
        self.calm_p, self.name = calm_p, name

    def system_one(self, state, questions, **_):
        angry_p = round(1 - self.calm_p, 6)
        return {"model": self.name, "usage": {"input_tokens": 1, "output_tokens": 1},
                "answers": {"billing": {"type": "noul", "noul": 0.97},
                            "tone": {"type": "choice", "choice": "calm" if self.calm_p >= 0.5 else "angry",
                                     "confidence": max(self.calm_p, angry_p), "probabilities": {"angry": angry_p, "calm": self.calm_p}}}}
