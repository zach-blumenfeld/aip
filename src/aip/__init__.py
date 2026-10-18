"""AIP: Agent Instruction Protocol runtime, server, and client. `aip.Client` is the SDK (`docs/sdk.md`)."""

__version__ = "0.1.0"

from aip.errors import AipError
from aip.sdk import (
    Client, Done, InvalidInput, InvalidSkill, NoServer, NotFound, Paused, RunError, ServerError, configure, settings,
)

__all__ = [
    "AipError", "Client", "Done", "InvalidInput", "InvalidSkill", "NoServer", "NotFound", "Paused", "RunError",
    "ServerError", "configure", "settings",
]
