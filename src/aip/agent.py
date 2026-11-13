"""aip agent: a chat model outside the run, answering the pauses of assist. This is all of it."""
from aip.chat import ChatError, continuation, message_for, parse, reason, refused, work_of
from aip.sdk import Paused, RunError

AGENT, ASSIST, MAX_REFUSALS = "agent", "assist", 3


def agent(client, chat, text, session, on_step=None, procedure=ASSIST):
    r = client.run(procedure, inputs(client, session, text), agent=AGENT, session=session, on_step=on_step)
    while isinstance(r, Paused):
        r, gave_up = answer(client, chat, r, AGENT, session, on_step)
        if gave_up:
            break                                                    # left paused, for whoever answers next
    return r


def answer(client, chat, paused, agent, session, on_step=None):
    """One pause: the model's answer resumes the run, a refused one goes back to it; (result, why it gave up)."""
    msg = message_for(client, paused)
    for _ in range(MAX_REFUSALS + 1):
        try:
            reply = chat(msg)
            return client.resume(paused, parse(reply), agent=agent, session=session, on_step=on_step,
                                 work=work_of(reply, paused)), None
        except ChatError as e:
            return paused, f"the model's endpoint failed: {e}"
        except (ValueError, RunError) as e:
            if getattr(e, "stopped", False):
                raise                                                # the answer went in; a later step failed the run
            msg, why = msg + refused(reply, e), reason(e)
    return paused, f"the model's answer at {paused.step} was refused {MAX_REFUSALS + 1} times; the last time: {why}"


def inputs(client, session, text):
    """What it asked last time and the person's reply, from the session's newest assist run in the record."""
    last = client.runs(name=ASSIST, session=session, limit=1)
    return continuation(client.run_record(last[0].run_id) if last else None, text)
