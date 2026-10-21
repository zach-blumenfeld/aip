"""AIP: Agent Instruction Protocol runtime, server, and client. `aip.Client` is the SDK (`docs/sdk.md`)."""

from importlib.metadata import version as _version

__version__ = _version("aip")

from aip.errors import AipError
from aip.sdk import (
    Client, Done, InvalidInput, InvalidSkill, NoServer, NotFound, Paused, RunError, ServerError, configure, settings,
)

__all__ = [
    "AipError", "Client", "Done", "InvalidInput", "InvalidSkill", "NoServer", "NotFound", "Paused", "RunError",
    "ServerError", "configure", "settings",
]
