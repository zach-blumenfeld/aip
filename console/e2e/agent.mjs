// A stand-in chat model for the console's driven runs (plan C6): the model `aip agent --answer` asks at each pause the
// launcher hands it (the Studio's build_procedure and edit_procedure, and a draft run from the Run button). An OpenAI
// Chat Completions endpoint (`POST /v1/chat/completions`) that answers from a script, the way tests/test_agent.py's
// stand-in does for the Python suite. Each request is one pause: the message is `# Procedure step: <step>`, then the
// state it reads as JSON and the keys to answer with; the model has no tools, so the reply is the answer, one JSON
// object. A refused answer comes back as a later message of the same request, which this stand-in never earns. So the
// replies depend on the request alone, and a run can be repeated.
//
//   node e2e/agent.mjs PORT
//
// What it drafts for build_procedure: a support-inbox procedure (a Task_Agent that classifies with labels [refund,
// bug, other], a route on them, a refund check by a script it also writes, a bug tag), as the folder's files
// (`drafted`, which build_procedure's `write` script puts on disk), named as the requester named it (`name` in the
// state) or, with none, `support_inbox` after what it handles. edit_procedure's `rewrite` reads procedure.aip from the
// folder's text (`before`) and adds a step for the `other` messages. The first extraction asks one question; once the
// person has answered, the second is settled. A brief that asks for an approval drafts `refund_approval` instead: a
// script, a task the model answers, and a task a person answers when the run console is told so; any task of a
// procedure the Studio built is answered with a value of each declared type.
//
// Every reply names the model that answered (`model`, as a real endpoint does: a dated snapshot of the name asked
// for), which aip records as the task's `answered_by.model`.

import { createServer } from "node:http";

const port = Number(process.argv[2] ?? 8767);

/** The id the stand-in reports in each reply, not the name it is configured with (`stand-in-1`). */
const REPORTED_MODEL = "stand-in-1-snapshot";
/** The name the stand-in gives a procedure when the requester gave none: the brief's subject. */
const SUBJECT_NAME = "support_inbox";

const PROCEDURE = (name) => `Procedure ${name}
  "Sort a support message: refund requests are checked against the limit of 100, bug reports are tagged by area, the rest ends."
  Requires python 3.10

Start "The message, as the inbox received it." {
  message: string "The customer's message."
  Next_Step classify
}

Task_Agent classify "Say what kind of message it is." {
  Read message
  Produce kind: choice [refund, bug, other] "What the message is about."
  Next_Step by_kind
}

Route by_kind "Refunds are checked, bug reports tagged, the rest ends." {
  Read kind
  refund -> check_refund
  bug -> tag_bug
  other -> end
}

Execute check_refund "Check the refund against the limit of 100." {
  Read message
  Run_Script scripts/check_refund.py
  Produce approved: boolean "Whether the refund is within the limit."
  Next_Step end
}

Task_Agent tag_bug "Tag the bug report with the area of the product it is about." {
  Read message
  Produce area: string "The area of the product."
  Next_Step end
}

End "The message, and what was done with it." {
  Read message
}
`;

const SCRIPT = `#!/usr/bin/env python3
"""Approve a refund of 100 or less. A stub: it approves everything until a developer reads the amount.

It touches nothing outside the working directory and uses no credentials.
"""
import json
import sys

json.load(sys.stdin)
json.dump({"approved": True}, sys.stdout)
`;

/** What a brief that asks for an approval drafts (the Run button, plans C5 and C6): a script, a task the model answers,
 *  and a task a person answers when the run console ticks it. */
const APPROVAL = (name) => `Procedure ${name}
  "Approve a refund request: a script checks it against the limit, the model summarizes it, a person approves it."
  Requires python 3.10

Start "The refund request, as the customer wrote it." {
  request: string "The customer's refund request."
  Next_Step check_limit
}

Execute check_limit "Check the refund against the limit of 100." {
  Read request
  Run_Script scripts/check_limit.py
  Produce within_limit: boolean "Whether the refund is within the limit."
  Next_Step summarize
}

Task_Agent summarize "Summarize the request for the approver in one sentence." {
  Read request, within_limit
  Produce summary: string "The request in one sentence, with whether it is within the limit."
  Next_Step approve
}

Task_Agent approve "Approve the refund or refuse it." {
  Read summary
  Produce approved: true_or_false "Whether the person approves the refund."
  Next_Step end
}

End "The summary and the person's decision." {
  Read summary, approved
}
`;

const APPROVAL_SCRIPT = `#!/usr/bin/env python3
"""Check a refund against the limit of 100. A stub: it calls every refund within the limit, and leaves a note
in the working directory that it ran.

It touches nothing outside the working directory and uses no credentials.
"""
import json
import os
import pathlib
import sys

json.load(sys.stdin)
pathlib.Path(os.environ.get("AIP_WORKDIR", "."), "limit-checked.txt").write_text("checked\\n")
json.dump({"within_limit": True}, sys.stdout)
`;

/** The name the stand-in gives the approval procedure. */
const APPROVAL_NAME = "refund_approval";

/** An answer to a task no script above knows, from its "Answer with" block: each key a value of its type. */
function typed(task) {
  const shape = /## Answer with\n```json\n([\s\S]*?)\n```/.exec(task)?.[1];
  const labels = JSON.parse(/^Labels: (.*)$/m.exec(task)?.[1] ?? "{}");
  const out = {};
  for (const [key, type] of Object.entries(shape ? JSON.parse(shape) : {})) {
    out[key] = labels[key]?.[0] ?? (type === "true_or_false" || type === "boolean" ? true : type === "list" ? [] : type === "object" ? {}
      : type === "integer" || type === "float" || type === "number" ? 1 : `the stand-in's ${key}`);
  }
  return out;
}

const OTHER = `Task_Agent answer_other "Answer a message that is neither a refund nor a bug report." {
  Read message
  Produce reply: string "The reply to send."
  Next_Step end
}

`;

const say = (answer) => ({
  model: REPORTED_MODEL,
  choices: [{ message: { role: "assistant", content: JSON.stringify(answer) }, finish_reason: "stop" }],
  usage: { prompt_tokens: 240, completion_tokens: 40 },
});

/** The reply to one pause. */
function reply(body) {
  const messages = body.messages ?? [];
  const task = messages.find((m) => m.role === "user")?.content ?? "";
  const step = /^# Procedure step: (\S+)/m.exec(task)?.[1] ?? "";
  const stateText = /## State it reads\n```json\n([\s\S]*?)\n```/.exec(task)?.[1];
  const state = stateText ? JSON.parse(stateText) : {};
  const approval = /\bapproval\b/i.test(state.brief ?? "");
  switch (step) {
    case "read_documents": {
      const doc = (state.files ?? [])[0];
      return say({ notes: doc ? `${doc.split("/").pop()}: refunds up to 100 are approved by a script; bug reports go to the team of their area.` : "No documents." });
    }
    case "extract_rules": {
      const answered = typeof state.answers === "string" && state.answers.trim() !== "";
      if (approval) {
        return answered
          ? say({ rules: "1. A script checks the refund against the limit of 100. 2. The model summarizes it. 3. A person approves it.", questions: [], settled: true })
          : say({ rules: "1. A script checks the refund. 2. A person approves it.", questions: ["Who approves a refund?"], settled: false });
      }
      return answered
        ? say({ rules: "1. A refund of 100 or less is approved by a script. 2. A bug report is tagged by area. 3. Anything else ends.", questions: [], settled: true })
        : say({ rules: "1. Refunds are checked by a script. 2. Bug reports are tagged.", questions: ["What is the refund limit, and who approves above it?"], settled: false });
    }
    case "draft": {
      const name = state.name || (approval ? APPROVAL_NAME : SUBJECT_NAME);
      const drafted = approval
        ? { "procedure.aip": APPROVAL(name), "scripts/check_limit.py": APPROVAL_SCRIPT }
        : { "procedure.aip": PROCEDURE(name), "scripts/check_refund.py": SCRIPT };
      return say({ procedure: name, drafted });
    }
    case "fix":
      return say("instruction" in state ? { fixed: "nothing to fix", repairs: {} } : { repairs: {} });
    case "review":
      if (/a person approves it/i.test(state.rules ?? "")) {
        return say({ review: "It checks the limit, summarizes the request and leaves the approval to a person.\nScripts:\nscripts/check_limit.py: writes limit-checked.txt in the working directory; uses no credentials." });
      }
      return say({ review: "It covers refunds and bug reports. The refund script is a stub that approves everything: a developer should make it read the amount before this is published.\nScripts:\nscripts/check_refund.py: approves every refund; touches nothing outside the working directory, uses no credentials." });
    case "rewrite": {
      const text = `${(state.before ?? {})["procedure.aip"] ?? ""}`;
      const changed = text.replace(/(\n\s*other\s*->\s*)end\b/, "$1answer_other").replace(/\nEnd "/, `\n${OTHER}End "`);
      return say({
        changes: "Added answer_other, a step that answers the messages that are neither refunds nor bug reports; the route sends `other` to it.\nScripts:\nnone written or changed.",
        rewritten: { "procedure.aip": changed },
      });
    }
    default:
      // A task of a procedure the Studio built, run from its Run button: an answer of the declared types.
      return say(typed(task));
  }
}

createServer((req, res) => {
  if (req.method === "GET" && req.url === "/v1/models") {
    res.writeHead(200, { "Content-Type": "application/json" });
    return res.end(JSON.stringify({ data: [{ id: "stand-in-1" }] }));
  }
  if (req.method !== "POST" || !req.url.endsWith("/chat/completions")) {
    res.writeHead(404);
    return res.end();
  }
  let text = "";
  req.on("data", (c) => { text += c; });
  req.on("end", () => {
    let body;
    try { body = JSON.parse(text); } catch { res.writeHead(400); return res.end(); }
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(reply(body)));
  });
}).listen(port, "127.0.0.1", () => console.log(`stand-in chat model on http://127.0.0.1:${port}/v1`));
