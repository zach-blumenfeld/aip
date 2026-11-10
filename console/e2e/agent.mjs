// A stand-in chat model for `aip runah`, which runs the Studio's chat (plans C4, A2): an OpenAI Chat Completions endpoint
// (`POST /v1/chat/completions`) that answers the tasks of build_procedure and edit_procedure from a
// script, the way tests/test_answerer.py's stand-in does for the Python suite. Each request is one turn
// of one task's chat: the task is the first user message (`# Task: <step>`, then the state it reads as
// JSON), and how far the chat has got is how many tool results it already holds. So the replies depend
// on the request alone, and a run can be repeated.
//
//   node e2e/agent.mjs PORT
//
// What it writes for build_procedure: a support-inbox procedure (a Task_Agent that classifies with
// labels [refund, bug, other], a route on them, a refund check by a script it also writes, a bug tag),
// compiled once with the compile tool, named as the requester named it (`name` in the draft's state)
// or, with none, `support_inbox` after what it handles. edit_procedure's `rewrite` reads procedure.aip
// and adds a step for the `other` messages. The first extraction asks one question; once the person
// has answered, the second is settled.
//
// Every reply names the model that answered (`model`, as a real endpoint does: a dated snapshot of the
// name asked for), which aip records as the task's `answered_by.model`.

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

const OTHER = `Task_Agent answer_other "Answer a message that is neither a refund nor a bug report." {
  Read message
  Produce reply: string "The reply to send."
  Next_Step end
}

`;

let calls = 0;

const tool = (name, args) => ({
  model: REPORTED_MODEL,
  choices: [{ message: { role: "assistant", content: null, tool_calls: [{ id: `call_${++calls}`, type: "function", function: { name, arguments: JSON.stringify(args) } }] },
              finish_reason: "tool_calls" }],
  usage: { prompt_tokens: 200, completion_tokens: 20 },
});
const say = (answer) => ({
  model: REPORTED_MODEL,
  choices: [{ message: { role: "assistant", content: JSON.stringify(answer) }, finish_reason: "stop" }],
  usage: { prompt_tokens: 240, completion_tokens: 40 },
});

/** The reply to one request of a task's chat. */
function reply(body) {
  const messages = body.messages ?? [];
  const task = messages.find((m) => m.role === "user")?.content ?? "";
  const step = /^# Task: (\S+)/m.exec(task)?.[1] ?? "";
  const stateText = /## State it reads\n```json\n([\s\S]*?)\n```/.exec(task)?.[1];
  const state = stateText ? JSON.parse(stateText) : {};
  const results = messages.filter((m) => m.role === "tool");
  const n = results.length;
  switch (step) {
    case "read_documents": {
      const doc = (state.files ?? [])[0];
      if (doc && n === 0) return tool("read_file", { path: doc });
      return say({ notes: doc ? `${doc.split("/").pop()}: refunds up to 100 are approved by a script; bug reports go to the team of their area.` : "No documents." });
    }
    case "extract_rules": {
      const answered = typeof state.answers === "string" && state.answers.trim() !== "";
      return answered
        ? say({ rules: "1. A refund of 100 or less is approved by a script. 2. A bug report is tagged by area. 3. Anything else ends.", questions: [], settled: true })
        : say({ rules: "1. Refunds are checked by a script. 2. Bug reports are tagged.", questions: ["What is the refund limit, and who approves above it?"], settled: false });
    }
    case "draft": {
      const out = state.out, name = state.name || SUBJECT_NAME;
      if (n === 0) return tool("write_file", { path: `${out}/procedure.aip`, content: PROCEDURE(name) });
      if (n === 1) return tool("write_file", { path: `${out}/scripts/check_refund.py`, content: SCRIPT });
      if (n === 2) return tool("compile", { path: out });
      return say({ path: out, procedure: name });
    }
    case "fix":
      return say(state.path !== undefined && "rules" in state ? { path: state.path } : { fixed: "nothing to fix" });
    case "review":
      return say({ review: "It covers refunds and bug reports. The refund script is a stub that approves everything: a developer should make it read the amount before this is published.\nScripts:\nscripts/check_refund.py: approves every refund; touches nothing outside the working directory, uses no credentials." });
    case "rewrite": {
      if (n === 0) return tool("read_file", { path: `${state.path}/procedure.aip` });
      if (n === 1) {
        const text = `${results[0].content}`;
        const changed = text.replace(/(\n\s*other\s*->\s*)end\b/, "$1answer_other").replace(/\nEnd "/, `\n${OTHER}End "`);
        return tool("write_file", { path: `${state.path}/procedure.aip`, content: changed });
      }
      return say({ changes: "Added answer_other, a step that answers the messages that are neither refunds nor bug reports; the route sends `other` to it.\nScripts:\nnone written or changed." });
    }
    default:
      return say({});
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
