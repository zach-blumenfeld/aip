"""AIP: Agent Instruction Protocol runtime, server, and client. `aip.Client` is the SDK (`docs/sdk.md`)."""

from importlib.metadata import version as _version

__version__ = _version("agent-instruction-protocol")  # the distribution; the module and command stay `aip`

from aip.errors import AipError
from aip.sdk import (
    Client, Compiled, CompileError, Description, Done, InvalidBundle, InvalidInput, NoServer, NotFound, Paused, RunError,
    ServerError, Task, configure, settings,
)

__all__ = [
    "AipError", "Client", "Compiled", "CompileError", "Description", "Done", "InvalidBundle", "InvalidInput", "NoServer",
    "NotFound", "Paused", "RunError", "ServerError", "Task", "configure", "settings",
]
