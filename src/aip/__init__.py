"""AIP: Agent Instruction Protocol runtime, server, and client. `aip.Client` is the SDK (`docs/sdk.md`)."""

from importlib.metadata import version as _version

__version__ = _version("agent-instruction-protocol")  # the distribution; the module and command stay `aip`

from aip.errors import AipError
from aip.sdk import (
    Client, Compiled, CompileError, DepthExceeded, Description, Done, InvalidBundle, InvalidInput, NoServer, NotFound, Paused, RetiredRevision,
    RunError, ServerError, Task, configure, configure_runah, settings,
)

__all__ = [
    "AipError", "Client", "Compiled", "CompileError", "DepthExceeded", "Description", "Done", "InvalidBundle", "InvalidInput", "NoServer",
    "NotFound", "Paused", "RetiredRevision", "RunError", "ServerError", "Task", "configure", "configure_runah", "settings",
]
