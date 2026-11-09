"""The bundle: the compiled form of a program (spec section 3), one Relate file.

`compile_folder(folder)` parses and checks `procedure.aip`, collects the files under `assets/`,
`references/` and `scripts/`, builds the graph and computes the bundle id. `write_bundle` puts
the graph in a new `.rl`; `read_bundle` opens one read-only and verifies it; `export_bundle`
writes the program directory back, byte for byte.

**The bundle id** is the sha256 of a manifest listing the sha256 of the source and of every file:

    aip bundle 1
    source <sha256 of procedure.aip's bytes>
    file <path> <sha256 of its bytes>        one line per file, sorted by path

So an unchanged program compiles to the same id on any machine and whatever wrote the file; the
`.rl`'s own bytes, a file's mode, the compiler's version and the time never enter it.

**Verification.** A bundle is the stored source and files plus a derived graph. `read_bundle`
recomputes the id from what is stored, parses and checks the stored source against the stored
file list, rebuilds the graph and compares it with the stored one; any difference is
`BundleError("bundle_tampered")`, so a bundle edited by hand in Cypher does not run. The
compiler's version is the one property left out of the comparison, since a later compiler
reading an older bundle is the ordinary case; a schema change between them shows up as a
mismatch and is a new language version's business."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePosixPath

from aip_spec import syntax as s
from aip_spec.checker import Diagnostic, check, check_source, has_errors
from aip_spec.errors import ParseError
from aip_spec.graph import PROCEDURE_ID, FileEntry, Graph, GraphEdge, GraphNode, build_graph
from aip_spec.language import LANGUAGE_VERSION
from aip_spec.parser import parse

SOURCE_FILE = "procedure.aip"
RESOURCE_DIRS = ("assets", "references", "scripts")
BUNDLE_SUFFIX = ".rl"
# Left out of the bundle: interpreter caches and Finder droppings, which no step can name.
SKIPPED_DIRS = ("__pycache__",)
SKIPPED_FILES = (".DS_Store",)


class BundleError(Exception):
    """A bundle that cannot be used. `code` is one of `not_a_bundle`, `bundle_language_version`,
    `bundle_tampered`, `export_target`."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


@dataclass
class Bundle:
    """A compiled program: the source, the files, the graph derived from them, and the id."""
    name: str
    source: str
    files: list[FileEntry]
    graph: Graph
    id: str
    language_version: str = LANGUAGE_VERSION
    compiler_version: str = ""

    def file(self, path: str) -> FileEntry | None:
        return next((f for f in self.files if f.path == path), None)


def compiler_version() -> str:
    try:
        return version("aip-spec")
    except PackageNotFoundError:  # pragma: no cover
        return "0+unknown"


def bundle_id(source: str, files: list[FileEntry]) -> str:
    manifest = ["aip bundle 1", "source " + hashlib.sha256(source.encode("utf-8")).hexdigest()]
    manifest += [f"file {f.path} {f.sha256}" for f in sorted(files, key=lambda f: f.path)]
    return hashlib.sha256(("\n".join(manifest) + "\n").encode("utf-8")).hexdigest()


def collect_files(folder: Path) -> list[FileEntry]:
    """Every file under the three resource directories, sorted by path."""
    out: list[FileEntry] = []
    for top in RESOURCE_DIRS:
        root = folder / top
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIPPED_DIRS)
            for filename in sorted(filenames):
                if filename in SKIPPED_FILES:
                    continue
                path = Path(dirpath) / filename
                if not path.is_file():
                    continue
                rel = PurePosixPath(path.relative_to(folder).as_posix())
                out.append(FileEntry(str(rel), path.read_bytes(), stat.S_IMODE(path.stat().st_mode)))
    out.sort(key=lambda f: f.path)
    return out


def _assemble(program: s.Program, source: str, files: list[FileEntry], compiler: str) -> Bundle:
    id = bundle_id(source, files)
    graph = build_graph(program, files, id, compiler)
    graph.node(PROCEDURE_ID).properties["source"] = source
    return Bundle(program.name, source, files, graph, id, LANGUAGE_VERSION, compiler)


def compile_source(source: str, files: list[FileEntry], file: str | None = None,
                   compiler: str | None = None) -> tuple[Bundle | None, list[Diagnostic]]:
    """Compile source text with its files already in hand (a bundle's contents, or a test).
    Paths named by the program are checked against `files`, not the disk."""
    try:
        program = parse(source, file)
    except ParseError as exc:
        return None, [Diagnostic(**exc.to_diagnostic())]
    diagnostics = check(program, None, file, files={f.path for f in files})
    if has_errors(diagnostics):
        return None, diagnostics
    return _assemble(program, source, files, compiler_version() if compiler is None else compiler), diagnostics


def compile_folder(folder: Path | str, source: str | None = None) -> tuple[Bundle | None, list[Diagnostic]]:
    """Compile a program directory (or its `procedure.aip`): the bundle when the program has no
    error, else None, and every diagnostic either way. `source` stands in for the file's text
    when given (an editor's unsaved buffer); the folder's other files are read from disk either
    way, and the diagnostics still name the file."""
    path = Path(folder)
    file = path / SOURCE_FILE if path.is_dir() else path
    folder = file.parent
    if source is None:
        data = file.read_bytes()
        try:
            source = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            return None, [Diagnostic("syntax_error", "error", f"{SOURCE_FILE} is not UTF-8: {exc.reason} at byte {exc.start}",
                                     str(file), 1, 1, 1, 1, None)]
    program, diagnostics = check_source(source, str(file), folder)
    if program is None or has_errors(diagnostics):
        return None, diagnostics
    return _assemble(program, source, collect_files(folder), compiler_version()), diagnostics


# ---------------------------------------------------------------- the file

def write_graph(conn, graph: Graph, bundle: str) -> None:
    """Write a graph into an open Relate or Neo4j connection: the one body of Cypher that puts a
    bundle's nodes and edges in a store, whether the store is a new `.rl`, the runtime's in-memory
    copy of a bundle, or a server's catalog (where many bundles share one store and every node
    is matched by `{bundle_id, id}`)."""
    by_labels: dict[tuple[str, ...], list[dict]] = {}
    for n in graph.nodes:
        by_labels.setdefault(n.labels, []).append(n.properties)
    for labels, rows in by_labels.items():
        conn.execute(f"UNWIND $rows AS r CREATE (n:{':'.join(labels)}) SET n = r", {"rows": rows})
    by_type: dict[str, list[dict]] = {}
    for e in graph.edges:
        by_type.setdefault(e.type, []).append({"start": e.start, "end": e.end, "properties": e.properties})
    for type, rows in by_type.items():
        conn.execute(f"UNWIND $rows AS r MATCH (a {{bundle_id: $bundle, id: r.start}}), (b {{bundle_id: $bundle, id: r.end}}) "
                     f"CREATE (a)-[e:{type}]->(b) SET e = r.properties", {"rows": rows, "bundle": bundle})


def write_bundle(bundle: Bundle, path: Path | str) -> Path:
    """Write the bundle as a new `.rl` at `path`, replacing a file already there."""
    from aip_spec import relate

    target = Path(path)
    with relate.create(target) as conn:
        write_graph(conn, bundle.graph, bundle.id)
    return target


def read_graph(conn, bundle: str) -> Graph:
    """The graph of one bundle, read back from a store `write_graph` wrote it to."""
    nodes = [GraphNode(r["id"], tuple(r["labels"]), dict(r["props"]))
             for r in conn.execute("MATCH (n) WHERE n.bundle_id = $b RETURN n.id AS id, labels(n) AS labels, properties(n) AS props",
                                   {"b": bundle})]
    edges = [GraphEdge(r["type"], r["start"], r["end"], dict(r["props"]))
             for r in conn.execute("MATCH (a)-[e]->(b) WHERE a.bundle_id = $b AND b.bundle_id = $b "
                                   "RETURN a.id AS start, type(e) AS type, b.id AS end, properties(e) AS props", {"b": bundle})]
    return Graph(nodes, edges)


def read_bundle(path: Path | str) -> Bundle:
    """Open a bundle read-only and verify it: the id against the stored source and files, and the
    stored graph against the one the stored source compiles to (`bundle_tampered` otherwise)."""
    from aip_spec import relate

    target = Path(path)
    try:
        with relate.open(target, read_only=True) as conn:
            procedures = conn.execute("MATCH (p:Procedure) RETURN properties(p) AS p").fetchall()
            if len(procedures) != 1:
                raise BundleError("not_a_bundle", f"{target} holds {len(procedures)} procedures; a bundle holds one")
            header = dict(procedures[0]["p"])
            stored_id = header.get("bundle_id")
            if not stored_id or header.get("source") is None:
                raise BundleError("not_a_bundle", f"{target}: the procedure node has no bundle_id or no source")
            stored = read_graph(conn, stored_id)
    except FileNotFoundError:
        raise BundleError("not_a_bundle", f"{target}: no such file")
    except Exception as exc:
        if isinstance(exc, BundleError):
            raise
        if type(exc).__name__ in ("OperationalError", "RuntimeError", "InterfaceError"):
            raise BundleError("not_a_bundle", f"{target} is not a bundle Relate can open: {exc}") from exc
        raise
    language = header.get("language_version")
    if language != LANGUAGE_VERSION:
        raise BundleError("bundle_language_version", f"{target} is language {language}; this compiler is language {LANGUAGE_VERSION}")
    source = header["source"]
    files = []
    for node in stored.with_label("File"):
        entry = FileEntry.from_properties(node.properties)
        if entry.sha256 != node.properties.get("sha256") or entry.size != node.properties.get("size"):
            raise BundleError("bundle_tampered", f"{target}: the bytes of {entry.path} do not match their recorded hash")
        files.append(entry)
    files.sort(key=lambda f: f.path)
    if bundle_id(source, files) != stored_id:
        raise BundleError("bundle_tampered", f"{target}: the stored source and files do not hash to the bundle id {stored_id}")
    compiler = header.get("compiler_version") or ""
    bundle, diagnostics = compile_source(source, files, f"{target}:{SOURCE_FILE}", compiler)
    if bundle is None:
        first = next(d for d in diagnostics if d.severity == "error")
        raise BundleError("bundle_tampered", f"{target}: the stored source does not compile ({first})")
    if bundle.graph.canonical() != stored.canonical():
        raise BundleError("bundle_tampered", f"{target}: the stored graph is not the one the stored source compiles to")
    return bundle


def export_bundle(bundle: Bundle, out: Path | str, force: bool = False) -> Path:
    """Write the program directory back: `procedure.aip` and every file, byte for byte, with its
    mode. `out` must not exist or must be empty, unless `force`."""
    target = Path(out)
    if target.exists() and any(target.iterdir()) and not force:
        raise BundleError("export_target", f"{target} exists and is not empty; choose another directory or pass --force")
    target.mkdir(parents=True, exist_ok=True)
    (target / SOURCE_FILE).write_bytes(bundle.source.encode("utf-8"))
    for f in bundle.files:
        path = target / Path(*PurePosixPath(f.path).parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f.data)
        try:
            os.chmod(path, f.mode)
        except OSError:  # pragma: no cover  (a filesystem without modes)
            pass
    return target
