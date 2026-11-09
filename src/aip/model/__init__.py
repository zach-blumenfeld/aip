"""The AIP runtime's engine: a compiled procedure behind a Relate connection, the state, the
steps, the answers, and the run loop.

    from aip_spec import compile_folder
    from aip.model import Engine, Procedure, ScriptedResolver

    bundle, diagnostics = compile_folder("examples/language/billing-support")
    with Procedure.load(bundle) as procedure:
        run = Engine(resolver=ScriptedResolver({...})).start(procedure, {"message": "..."})

`docs/language/runtime.md` says what a runtime must do; `aip.model.engine` is where this one
does it."""

from aip.model import answers
from aip.model.cache import aip_home, cache_dir, unpack
from aip.model.engine import DONE, FAILED, PAUSED, RUNNING, Engine, Run
from aip.model.environment import Requires, default_step_timeout
from aip.model.procedure import Procedure, Step
from aip.model.resolver import Decision, DecisionRequest, Resolver, ScriptedResolver
from aip.model.types import (
    ERROR_KINDS, JSON, DecisionModelFailed, InvalidInput, InvalidOutput, NoBranch, NoDecisionModel, NotPaused, RequiresUnmet,
    ScriptFailed, ScriptTimeout, StepError, branch_key, conforms, normalise,
)

__all__ = [
    "answers", "aip_home", "cache_dir", "unpack", "DONE", "FAILED", "PAUSED", "RUNNING", "Engine", "Run", "Requires",
    "default_step_timeout", "Procedure", "Step", "Decision", "DecisionRequest", "Resolver", "ScriptedResolver", "ERROR_KINDS",
    "JSON", "DecisionModelFailed", "InvalidInput", "InvalidOutput", "NoBranch", "NoDecisionModel", "NotPaused", "RequiresUnmet",
    "ScriptFailed", "ScriptTimeout", "StepError", "branch_key", "conforms", "normalise",
]
