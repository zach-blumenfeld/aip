"""aip agent: a chat model outside the run answering the pauses of assist. This is all of it."""
from aip.chat import history, message_for, parse, refused, work_of
from aip.sdk import Paused, RunError


def agent(client, chat, text, session):
    r = client.run("assist", {"task": text, "outcome": history(client, session, text)}, agent="agent", session=session)
    while isinstance(r, Paused):
        msg = message_for(client, r)
        for _ in range(4):                                   # one answer, up to three corrections
            reply = chat(msg)
            try:
                r = client.resume(r, parse(reply), agent="agent", session=session, work=work_of(reply, r))
                break
            except RunError as e:
                msg = msg + refused(reply, e)
        else:
            break                                            # left paused, for whoever answers next
    return r
