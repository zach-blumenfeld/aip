#!/usr/bin/env node
// A decision model for the e2e run: an endpoint with the TypeSafe API shape (`POST /v1/systemone`:
// state and questions in, one answer object per question out), which is all `aip` asks of a model
// (`AIP_DECISION_MODEL`). It reads no language: the text under judgment carries marks that say what
// to answer, so a spec steers every branch of a procedure from the inputs it types.
//
//   a true_or_false question holds at 0.97, unless the state holds
//     [break:WORD]    and the question's instruction contains WORD: it does not hold (0.04)
//     [unsure:WORD]   and the question's instruction contains WORD: it holds at 0.6 (under most bars)
//   a choice is its last label at 0.97, unless the state holds
//     [LABEL]         then that label
//     [unsure]        then the confidence is 0.55
//   a score is its middle level, or the level [LABEL] names, the same way
//
//   node e2e/model.mjs [PORT]     (default 8766; prints the address when listening)
import { createServer } from "node:http";

export const MODEL_NAME = "e2e-1";

const escape = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** The words of every `[kind:WORD]` mark in `text`. */
function marks(text, kind) {
  return [...text.matchAll(new RegExp(`\\[${kind}:([^\\]]+)\\]`, "g"))].map((m) => m[1]);
}

function spread(labels, chosen, confidence) {
  const rest = labels.length > 1 ? (1 - confidence) / (labels.length - 1) : 0;
  return Object.fromEntries(labels.map((l) => [l, l === chosen ? confidence : Number(rest.toFixed(4))]));
}

/** One question's answer, from the marks in the state. */
export function answer(question, stateText) {
  const instruction = `${question.instructions ?? ""}`;
  if (question.type === "noul") {
    if (marks(stateText, "break").some((w) => instruction.includes(w))) return { type: "noul", noul: 0.04 };
    if (marks(stateText, "unsure").some((w) => instruction.includes(w))) return { type: "noul", noul: 0.6 };
    return { type: "noul", noul: 0.97 };
  }
  const confidence = stateText.includes("[unsure]") ? 0.55 : 0.97;
  if (question.type === "choice") {
    const labels = Object.keys(question.criteria ?? {});
    const chosen = labels.find((l) => new RegExp(`\\[${escape(l)}\\]`).test(stateText)) ?? labels[labels.length - 1];
    return { type: "choice", choice: chosen, confidence, probabilities: spread(labels, chosen, confidence) };
  }
  if (question.type === "score") {
    const levels = (question.criteria ?? []).map((c) => `${c}`);
    const named = levels.findIndex((l) => new RegExp(`\\[${escape(l)}\\]`).test(stateText));
    const level = named >= 0 ? named : Math.floor(levels.length / 2);
    const numbers = levels.map((_, i) => String(i));
    return { type: "score", score: level, confidence, legend: Object.fromEntries(levels.map((l, i) => [String(i), l])),
             probabilities: spread(numbers, String(level), confidence) };
  }
  throw new Error(`unknown question type ${question.type}`);
}

export function serve(port) {
  const server = createServer(async (req, res) => {
    const reply = (status, body) => {
      res.writeHead(status, { "Content-Type": "application/json" });
      res.end(JSON.stringify(body));
    };
    if (req.method === "GET" && req.url === "/v1/models") return reply(200, { models: [{ id: MODEL_NAME }] });
    if (req.method !== "POST" || req.url !== "/v1/systemone") return reply(404, { error: { message: `no ${req.method} ${req.url}` } });
    let text = "";
    for await (const chunk of req) text += chunk;
    try {
      const body = JSON.parse(text);
      const stateText = JSON.stringify(body.state ?? {});
      const answers = Object.fromEntries(Object.entries(body.questions ?? {}).map(([name, q]) => [name, answer(q, stateText)]));
      reply(200, { model: MODEL_NAME, usage: { input_tokens: text.length, output_tokens: 1 }, answers });
    } catch (e) {
      reply(400, { error: { message: e instanceof Error ? e.message : String(e) } });
    }
  });
  return new Promise((resolve) => server.listen(port, "127.0.0.1", () => resolve(server)));
}

if (process.argv[1] && import.meta.filename === process.argv[1]) {
  const port = Number(process.argv[2] ?? process.env.MODEL_E2E_PORT ?? 8766);
  serve(port).then(() => console.log(`e2e model: http://127.0.0.1:${port}`));
}
