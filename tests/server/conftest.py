"""The server's tests run the one app over each backend: Relate in memory, and Neo4j when
`NEO4J_URI` names a database to use (with `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`).
The Neo4j half deletes every node the store writes, before and after each test, so point it at
a database kept for tests. Everything here needs Relate, which a bundle is written in."""

import os

import pytest

from aip.compiler import relate

needs_neo4j = pytest.mark.skipif(not os.environ.get("NEO4J_URI"), reason="NEO4J_URI not set")


def pytest_collection_modifyitems(items):
    skip = pytest.mark.skip(reason=relate.INSTALL_HINT)
    for item in items:
        if "backend" in getattr(item, "fixturenames", ()) and not relate.available():
            item.add_marker(skip)


@pytest.fixture(params=["relate", pytest.param("neo4j", marks=needs_neo4j)])
def backend(request):
    """An empty store on each backend."""
    if request.param == "relate":
        from aip.server.backends.relate import RelateBackend

        store = RelateBackend(":memory:")
    else:
        from aip.server.backends.neo4j import Neo4jBackend

        store = Neo4jBackend()
        store.store.clear()
    yield store
    if request.param == "neo4j":
        store.store.clear()
    store.close()


@pytest.fixture
def served(backend):
    """The app over the backend: `secret` is zach's token (every scope), `reader` reads only,
    `runner` reads and records runs."""
    from aip.server.app import READ, RUN, Token
    from served import Served

    return Served(backend, token_names={"secret": "zach"},
                  tokens={"reader": Token(frozenset({READ})), "runner": Token(frozenset({READ, RUN}), "ci")})
