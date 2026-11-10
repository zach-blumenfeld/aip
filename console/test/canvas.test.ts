// The card canvas's model and layout, on graphs as `aip compile --json` printed them for three of the
// example programs (test/fixtures/*.graph.json; scratch them again from the examples when the graph's
// schema moves: aip docs/language/bundle.md).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { cardHeight, depthOf, layoutOf, SIZE } from "../src/canvas/layout.ts";
import { modelOf, sliceOf, type Graph } from "../src/canvas/model.ts";

const graph = (name: string) => JSON.parse(readFileSync(path.join(import.meta.dirname, "fixtures", `${name}.graph.json`), "utf8")) as Graph;

test("one card per step: kind, description as title, what it reads and produces", () => {
  const model = modelOf(graph("billing-support"));
  assert.equal(model.name, "billing_support");
  assert.deepEqual(model.top, ["step:start", "step:triage", "step:by_tone", "step:escalate", "step:reply", "step:end"]);
  assert.deepEqual(Object.keys(model.frames), []);

  const triage = model.cards["step:triage"];
  assert.equal(triage.kind, "Decide");
  assert.equal(triage.title, "Classify whether the message is about billing and how upset the customer is.");
  assert.deepEqual(triage.sections, [
    { label: "reads", rows: ["message"] },
    { label: "asks", rows: ["billing: true_or_false", "tone: choice [angry, calm]"] },
    { label: "produces", rows: ["triage_decision: decision"] },
  ]);
  assert.deepEqual(model.cards["step:start"].sections, [{ label: "inputs", rows: ["message: string"] }]);
  assert.deepEqual(model.cards["step:escalate"].sections, [
    { label: "reads", rows: ["message", "triage_decision.tone"] },
    { label: "runs", rows: ["scripts/escalate.py"] },
    { label: "uses", rows: ["assets/config.json"] },
    { label: "produces", rows: ["ticket_id: integer", "queue: string"] },
  ]);
  assert.deepEqual(model.cards["step:reply"].sections.find((s) => s.label === "prompt"), { label: "prompt", rows: ["assets/reply.md"] });
});

test("a port per way out, quoting where it leads; a route has one per label and one for its check", () => {
  const model = modelOf(graph("billing-support"));
  const next = model.cards["step:triage"].ports;
  assert.equal(next.length, 1);
  assert.deepEqual({ kind: next[0].kind, label: next[0].label, target: next[0].target }, { kind: "next", label: "next", target: "step:by_tone" });
  assert.match(next[0].quote, /^Angry customers, and those the model is unsure of/);
  assert.equal(typeof next[0].line, "number");

  const route = model.cards["step:by_tone"];
  assert.deepEqual(route.sections, [{ label: "reads", rows: ["triage_decision.tone"] }, { label: "routes on", rows: ["measured answer"] }]);
  assert.deepEqual(route.ports.map((p) => [p.kind, p.label, p.target]), [
    ["below", "confidence below 0.9", "step:escalate"],
    ["branch", "angry", "step:escalate"],
    ["branch", "calm", "step:reply"],
  ]);
  assert.equal(route.ports[2].quote, model.cards["step:reply"].title);
  assert.deepEqual(model.cards["step:end"].ports, []);
});

test("a loop is a frame around its body, with its header and its own way out", () => {
  const model = modelOf(graph("fixed-policy"));
  assert.deepEqual(model.top, ["step:start", "step:draft", "loop:revise", "step:end"]);
  const revise = model.frames["loop:revise"];
  assert.equal(revise.kind, "Loop");
  assert.equal(revise.header, "Until check_summary.all_hold, At_Most 3, Else_Fail");
  assert.deepEqual(revise.children, ["step:check", "step:summarize_check", "step:fix"]);
  assert.deepEqual(revise.ports.map((p) => [p.kind, p.target]), [["next", "step:end"]]);
  assert.equal(model.cards["step:fix"].parent, "loop:revise");
  assert.deepEqual(model.cards["step:fix"].ports.map((p) => [p.kind, p.target, p.quote]), [["continue", "loop:revise", "the next pass of revise"]]);
  assert.equal(model.cards["step:draft"].ports[0].quote, "loop revise");
  assert.deepEqual(model.cards["step:summarize_check"].sections[1], { label: "aggregates", rows: ["all_hold: All policy_check With Confidence_Above 0.7"] });
});

test("loops nest: a Loop inside a For, its check and fix inside it, a For's header", () => {
  const model = modelOf(graph("ticket-triage"));
  assert.deepEqual(model.top, ["step:start", "loop:each_ticket", "step:summarize", "step:end"]);
  const each = model.frames["loop:each_ticket"];
  assert.equal(each.kind, "For");
  assert.equal(each.header, "Over tickets As ticket, At_Most 50, Collect reply Into replies");
  assert.deepEqual(each.children, ["step:classify", "step:by_tone", "step:draft", "step:escalate", "loop:revise"]);
  const revise = model.frames["loop:revise"];
  assert.equal(revise.parent, "loop:each_ticket");
  assert.equal(revise.header, "Until passed, At_Most 4, Else_Fail");
  assert.deepEqual(revise.children, ["step:check", "step:fix"]);
  assert.deepEqual(revise.ports.map((p) => [p.kind, p.target]), [["continue", "loop:each_ticket"]]);
  // The check is in the loop it serves, and the fix ends the pass: the only way back is to the loop.
  assert.deepEqual(model.cards["step:check"].ports.map((p) => [p.kind, p.target]), [["next", "step:fix"]]);
  assert.deepEqual(model.cards["step:fix"].ports.map((p) => [p.kind, p.target]), [["continue", "loop:revise"]]);
  assert.equal(model.cards["step:start"].ports[0].quote, "for each_ticket");
  assert.equal(depthOf(model, "step:start"), 0);
  assert.equal(depthOf(model, "step:classify"), 1);
  assert.equal(depthOf(model, "step:fix"), 2);
});

test("the layout: one column, bodies inside their frames, a wire per port in a lane of its own", () => {
  for (const name of ["billing-support", "fixed-policy", "ticket-triage"]) {
    const model = modelOf(graph(name));
    const layout = layoutOf(model);
    const items = [...Object.values(model.cards), ...Object.values(model.frames)];

    for (const item of items) {
      const box = layout.boxes[item.id];
      assert.ok(box, `${name}: ${item.id} has a box`);
      assert.equal(layout.portY[item.id].length, item.ports.length);
      for (const y of layout.portY[item.id]) assert.ok(y > box.y && y < box.y + box.h, `${name}: a port of ${item.id} is on it`);
      if (item.parent !== null) {
        const outer = layout.boxes[item.parent];
        assert.ok(box.x >= outer.x + SIZE.inset && box.y >= outer.y + SIZE.frameHead && box.x + box.w <= outer.x + outer.w - SIZE.inset &&
                  box.y + box.h <= outer.y + outer.h, `${name}: ${item.id} is inside ${item.parent}`);
      }
      assert.ok(box.x + box.w < layout.width && box.y + box.h < layout.height, `${name}: ${item.id} is in the picture`);
    }
    for (const card of Object.values(model.cards)) assert.equal(layout.boxes[card.id].h, cardHeight(card));

    // The top column runs down the page in written order, nothing overlapping.
    for (let i = 1; i < model.top.length; i++) {
      const above = layout.boxes[model.top[i - 1]], below = layout.boxes[model.top[i]];
      assert.equal(below.y, above.y + above.h + SIZE.gap, `${name}: ${model.top[i]} follows ${model.top[i - 1]}`);
    }

    assert.equal(layout.wires.length, items.reduce((n, item) => n + item.ports.length, 0), `${name}: a wire per port`);
    const right = Math.max(...items.map((item) => layout.boxes[item.id].x + layout.boxes[item.id].w));
    const spans = layout.wires.map((wire) => {
      const m = /^M (\S+) (\S+) H (\S+) V (\S+) H (\S+)$/.exec(wire.path);
      assert.ok(m, `${name}: ${wire.path}`);
      const [sx, y1, gx, y2, tx] = m.slice(1).map(Number);
      assert.equal(sx, layout.boxes[wire.from].x + layout.boxes[wire.from].w);
      assert.equal(y1, layout.portY[wire.from][wire.port]);
      assert.ok(gx > right, `${name}: the wire runs in the gutter, clear of every card`);
      assert.ok(tx > layout.boxes[wire.to].x + layout.boxes[wire.to].w, `${name}: the wire ends at its target's right edge`);
      return { gx, top: Math.min(y1, y2), bottom: Math.max(y1, y2) };
    });
    for (const a of spans) for (const b of spans) {
      if (a !== b && a.gx === b.gx) assert.ok(a.bottom < b.top || a.top > b.bottom, `${name}: two wires share a lane and overlap`);
    }
  }
});

test("a card's height is its rows: the numbers canvas.css repeats", () => {
  const model = modelOf(graph("billing-support"));
  // start: padding, head, title, one section of one row (label + row), one port, padding.
  assert.equal(cardHeight(model.cards["step:start"]), 10 + 24 + 40 + (6 + 18 * 2) + (6 + 22) + 10);
  // end: no ports, one section of four rows.
  assert.equal(cardHeight(model.cards["step:end"]), 10 + 24 + 40 + (6 + 18 * 5) + 10);
});

test("the source slice of a card is the lines that wrote it", () => {
  const source = "a\nb\nc\nd\n";
  assert.deepEqual(sliceOf(source, 2, 3), { text: "b\nc", first: 2 });
  assert.deepEqual(sliceOf(source, 4, null), { text: "d", first: 4 });
  assert.equal(sliceOf(source, null, null), null);
  assert.equal(sliceOf(source, 40, 41), null);
  assert.deepEqual(modelOf({ nodes: [], edges: [] }), { name: "", description: "", cards: {}, frames: {}, top: [] });
});
