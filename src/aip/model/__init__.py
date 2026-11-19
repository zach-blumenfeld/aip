"""The AIP runtime's engine: a compiled procedure behind a Relate connection, the state, the
steps, the answers, and the run loop.

    from aip.compiler import compile_folder
    from aip.model import Engine, Procedure, ScriptedResolver

    bundle, diagnostics = compile_folder("examples/language/billing-support")
    with Procedure.load(bundle) as procedure:
        run = Engine(resolver=ScriptedResolver({...})).start(procedure, {"message": "..."})

`docs/language/runtime.md` says what a runtime must do; `aip.model.engine` is where this one
does it."""

from aip.model import answers
from aip.model.cache import aip_home, cache_dir, unpack
from aip.model.engine import DEFAULT_BATCH, DONE, FAILED, IDENTITY_FIELDS, PAUSED, RUNNING, Cursor, Engine, Run, new_identity
from aip.model.environment import Requires, script_timeout
from aip.model.procedure import Loop, Procedure, Step
from aip.model.resolver import Decision, DecisionRequest, Resolver, ScriptedResolver
from aip.model.types import (
    ERROR_KINDS, JSON, DecisionModelFailed, InvalidInput, InvalidOutput, LoopCap, NoBranch, NoDecisionModel, NotPaused,
    RequiresUnmet, ScriptFailed, ScriptTimeout, StepError, branch_key, conforms, normalise,
)
from aip.model.typesafe import TypeSafeResolver

__all__ = [
    "answers", "aip_home", "cache_dir", "unpack", "DEFAULT_BATCH", "DONE", "FAILED", "IDENTITY_FIELDS", "PAUSED", "RUNNING",
    "Cursor", "Engine", "Run", "new_identity", "Requires", "script_timeout", "Loop", "Procedure", "Step", "Decision",
    "DecisionRequest", "Resolver", "ScriptedResolver", "TypeSafeResolver", "ERROR_KINDS", "JSON", "DecisionModelFailed",
    "InvalidInput", "InvalidOutput", "LoopCap", "NoBranch", "NoDecisionModel", "NotPaused", "RequiresUnmet", "ScriptFailed",
    "ScriptTimeout", "StepError", "branch_key", "conforms", "normalise",
]
