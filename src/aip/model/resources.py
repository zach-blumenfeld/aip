"""Package resources (assets, references, scripts) and the loader that reads them."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List


class Resource(ABC):
    """
    A file that belongs to an AIP package, addressed relative to the package root as
    `<aip_id>/<assets|references|scripts>/<name>` (plural folders, per Agent Skills).
    Bodies are read from disk by ResourceLoader.
    """
    uri: Path
    description: str

    def __init__(self, aip_id: str, name: str, description: str = ""):
        self.uri = Path(aip_id, self._folder(), name)
        self.description = description

    @property
    def name(self) -> str:
        return self.uri.stem

    @abstractmethod
    def _folder(self) -> str:
        pass

    def summary(self) -> Dict[str, str]:
        """Lazy form: enough for a client to decide whether to fetch the body."""
        return {"uri": str(self.uri), "description": self.description}


class Asset(Resource):
    """Fixed templates and resources injected into every invoke."""
    def _folder(self) -> str:
        return "assets"


class Reference(Resource):
    """Documents the client loads on demand (progressive disclosure)."""
    def _folder(self) -> str:
        return "references"


class Script(Resource):
    """An executable python script in the package, run by an Execution step."""
    def _folder(self) -> str:
        return "scripts"


class ResourceLoader:
    """
    Reads resource files from disk, relative to a package root, and caches them.
    The single place to add size limits or non-file backends later.

    Assets are loaded eagerly by steps at render time. References are loaded on demand
    when the client asks for one by uri (`load_uri`).
    """
    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        self._cache: Dict[Path, str] = {}

    def path(self, uri: Path | str) -> Path:
        """Resolve a package-relative uri to an absolute path inside the root."""
        path = (self.root / uri).resolve()
        if self.root not in path.parents:
            raise ValueError(f"Resource uri {uri!s} escapes package root {self.root}")
        return path

    def load_uri(self, uri: Path | str, fresh: bool = False) -> str:
        """Read a resource body. `fresh=True` bypasses the cache and re-reads from disk."""
        uri = Path(uri)
        if fresh or uri not in self._cache:
            path = self.path(uri)
            if not path.is_file():
                raise FileNotFoundError(f"Resource {uri!s} not found at {path}")
            self._cache[uri] = path.read_text(encoding="utf-8")
        return self._cache[uri]

    def load(self, resource: Resource, fresh: bool = False) -> str:
        return self.load_uri(resource.uri, fresh=fresh)

    def load_all(self, resources: List[Resource], fresh: bool = False) -> Dict[str, str]:
        return {r.name: self.load(r, fresh=fresh) for r in resources}
