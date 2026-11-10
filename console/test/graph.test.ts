// The step graph: its model, layout, data flow and a run's path, on graphs as `aip compile --json`
// printed them for three of the example programs and on records the real runtime wrote
// (test/fixtures/; scratch them again from the examples when the graph's schema or the record moves).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import type { RunRecord } from "../src/api/types.ts";
import { layoutOf as cardLayoutOf } from "../src/canvas/layout.ts";
import { modelOf, type Graph } from "../src/canvas/model.ts";
import { dataEdges, dataKeys } from "../src/graph/dataflow.ts";
import { layoutOf, SIZE, type Box, type Direction } from "../src/graph/layout.ts";
import { edgeLabel, stepGraphOf } from "../src/graph/model.ts";
import { emptyTraffic, fold, pathOf } from "../src/graph/traffic.ts";

const fixture = (file: string) => JSON.parse(readFileSync(path.join(import.meta.dirname, "fixtures", file), "utf8"));
const graph = (name: string) => fixture(`${name}.graph.json`) as Graph;
const run = (name: string) => { const r = fixture(`${name}.run.json`); return (r.run ?? r) as RunRecord; };
const EXAMPLES = ["billing-support", "fixed-policy", "ticket-triage"];
const DIRECTIONS: Direction[] = ["down", "right"];

test("steps are nodes, loops are frames, and the control edges are the arrows", () => {
  const g = stepGraphOf(graph("billing-support"));
  assert.deepEqual(g.top, ["step:start", "step:triage", "step:by_tone", "step:escalate", "step:reply", "step:end"]);
  assert.equal(g.nodes["step:by_tone"].kind, "Route");
  assert.deepEqual(g.edges.map((e) => [e.key, edgeLabel(e)]), [
    ["step:start->step:triage", ""],
    ["step:triage->step:by_tone", ""],
    // The check and the `angry` branch lead to the same step: one arrow, two ways.
    ["step:by_tone->step:escalate", "< 0.9 · angry"],
    ["step:by_tone->step:reply", "calm"],
    ["step:escalate->step:end", ""],
    ["step:reply->step:end", ""],
  ]);
  assert.deepEqual(g.edges[2].ways.map((w) => w.kind), ["below", "branch"]);
});

test("a loop's arrows: into its body, Continue back to its head, Again to an earlier step, and its exit", () => {
  const g = stepGraphOf(graph("ticket-triage"));
  const edge = (from: string, to: string) => g.edges.find((e) => e.from === from && e.to === to);
  assert.deepEqual(g.nodes["loop:each_ticket"].children, ["step:classify", "step:by_tone", "step:draft", "step:escalate", "step:check", "loop:revise"]);
  assert.equal(g.nodes["loop:revise"].parent, "loop:each_ticket");
  assert.equal(g.nodes["loop:revise"].title, "Until passed, At_Most 3, Else_Fail");

  assert.equal(edge("loop:each_ticket", "step:classify")?.enter, true);
  assert.equal(edge("loop:revise", "step:fix")?.enter, true);
  // The pass is over: from a step, and from the inner loop's exit line.
  assert.deepEqual([edge("step:escalate", "loop:each_ticket")?.toFrame, edgeLabel(edge("step:escalate", "loop:each_ticket")!)], [true, "continue"]);
  assert.equal(edge("loop:revise", "loop:each_ticket")?.toFrame, true);
  assert.equal(edgeLabel(edge("step:fix", "step:check")!), "again");
  assert.equal(edge("step:fix", "step:check")?.toFrame, false);
  // A step into a loop, and a loop's exit, are arrows to and from the frame.
  assert.equal(edge("step:check", "loop:revise")?.toFrame, false);
  assert.ok(edge("loop:each_ticket", "step:summarize"));
  assert.equal(edgeLabel(edge("step:by_tone", "step:escalate")!), "< 0.6 · angry");
});

const within = (inner: Box, outer: Box) =>
  inner.x >= outer.x && inner.y >= outer.y && inner.x + inner.w <= outer.x + outer.w && inner.y + inner.h <= outer.y + outer.h;
const apart = (a: Box, b: Box) => a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y;

test("the layout, down and right: a body inside its frame, nothing overlapping, every arrow in the picture", () => {
  for (const name of EXAMPLES) for (const direction of DIRECTIONS) {
    const g = stepGraphOf(graph(name));
    const layout = layoutOf(g, direction);
    const where = `${name} ${direction}`;
    const ids = Object.keys(g.nodes);
    for (const id of ids) {
      const box = layout.boxes[id];
      assert.ok(box, `${where}: ${id} has a box`);
      assert.ok(box.x >= 0 && box.y >= 0 && box.x + box.w <= layout.width && box.y + box.h <= layout.height, `${where}: ${id} is in the picture`);
      if (!g.nodes[id].frame) assert.deepEqual([box.w, box.h], [SIZE.nodeWidth, SIZE.nodeHeight]);
      const parent = g.nodes[id].parent;
      if (parent !== null) {
        assert.ok(within(box, layout.boxes[parent]), `${where}: ${id} is inside ${parent}`);
        // Under the frame's header, which runs along its top either way.
        assert.ok(box.y >= layout.boxes[parent].y + SIZE.head, `${where}: ${id} is under the header of ${parent}`);
      }
    }
    // Two nodes overlap only when one is a frame that holds the other.
    for (const a of ids) for (const b of ids) {
      if (a >= b) continue;
      const nested = (x: string, y: string) => { for (let p = g.nodes[x].parent; p !== null; p = g.nodes[p].parent) if (p === y) return true; return false; };
      if (nested(a, b) || nested(b, a)) continue;
      assert.ok(apart(layout.boxes[a], layout.boxes[b]), `${where}: ${a} and ${b} do not overlap`);
    }
    assert.equal(layout.edges.length, g.edges.length, `${where}: every arrow is drawn`);
    for (const e of layout.edges) {
      for (const [x, y] of e.points) assert.ok(x >= 0 && y >= 0 && x <= layout.width && y <= layout.height, `${where}: ${e.edge.key} is in the picture`);
    }
    // The flow runs the way it is drawn: a step is past the one before it.
    const start = layout.boxes["step:start"], end = layout.boxes["step:end"];
    if (direction === "down") assert.ok(end.y > start.y + start.h, where); else assert.ok(end.x > start.x + start.w, where);
  }
});

test("the layout: Continue and Again run along rails, a forward arrow from box to box", () => {
  const g = stepGraphOf(graph("ticket-triage"));
  const layout = layoutOf(g, "down");
  const placed = (key: string) => layout.edges.find((e) => e.edge.key === key)!;
  const frame = layout.boxes["loop:each_ticket"];

  const next = placed("step:classify->step:by_tone");
  assert.equal(next.rail, false);
  assert.equal(next.points.length, 2);
  assert.equal(next.points[0][1], layout.boxes["step:classify"].y + SIZE.nodeHeight);
  assert.equal(next.points[1][1], layout.boxes["step:by_tone"].y);

  // Continue: out of the step's side, up a rail inside the frame, to the frame's head.
  const over = placed("step:escalate->loop:each_ticket");
  assert.equal(over.rail, true);
  assert.equal(over.points.length, 3);
  assert.equal(over.points[2][1], frame.y + SIZE.head);
  assert.ok(over.points[1][0] > frame.x && over.points[1][0] < frame.x + frame.w);

  // Again: from inside the inner loop back up to `check`, which is before it.
  const again = placed("step:fix->step:check");
  assert.equal(again.rail, true);
  const last = again.points[again.points.length - 1];
  assert.equal(last[1], layout.boxes["step:check"].y);
  assert.ok(last[0] > layout.boxes["step:check"].x && last[0] < layout.boxes["step:check"].x + SIZE.nodeWidth);
});

test("the card canvas draws to the right as one row, bodies inside their frames, wires under it", () => {
  for (const name of EXAMPLES) {
    const model = modelOf(graph(name));
    const layout = cardLayoutOf(model, "right");
    for (let i = 1; i < model.top.length; i++) {
      const before = layout.boxes[model.top[i - 1]], after = layout.boxes[model.top[i]];
      assert.ok(after.x >= before.x + before.w, `${name}: ${model.top[i]} is right of ${model.top[i - 1]}`);
      assert.equal(after.y, before.y);
    }
    for (const item of [...Object.values(model.cards), ...Object.values(model.frames)]) {
      const box = layout.boxes[item.id];
      assert.ok(box.x + box.w < layout.width && box.y + box.h < layout.height, `${name}: ${item.id} is in the picture`);
      if (item.parent !== null) assert.ok(within(box, layout.boxes[item.parent]), `${name}: ${item.id} is inside ${item.parent}`);
    }
    const ports = [...Object.values(model.cards), ...Object.values(model.frames)].reduce((n, item) => n + item.ports.length, 0);
    assert.equal(layout.wires.length, ports);
    // The column layout is untouched by the option.
    assert.deepEqual(cardLayoutOf(model, "down"), cardLayoutOf(model));
  }
});

test("data flow: who produces each key and who reads it, with whose answer steers a route", () => {
  const keys = dataKeys(graph("billing-support"));
  const key = (name: string) => keys.find((k) => k.key === name)!;
  assert.deepEqual(key("message").producers, ["step:start"]);
  assert.deepEqual(key("triage_decision").producers, ["step:triage"]);
  const route = key("triage_decision").readers.find((r) => r.node === "step:by_tone")!;
  assert.deepEqual(route, { node: "step:by_tone", field: "tone", how: "read", source: "measured" });
  assert.ok(key("message").readers.some((r) => r.node === "step:triage"));

  const edges = dataEdges(keys);
  assert.deepEqual(edges.find((e) => e.from === "step:triage" && e.to === "step:by_tone")?.keys, ["triage_decision"]);
  assert.ok(edges.every((e) => e.from !== e.to));
});

test("data flow through loops: the list a For runs over, the item it binds, what it collects, what an Until watches", () => {
  const keys = dataKeys(graph("ticket-triage"));
  const key = (name: string) => keys.find((k) => k.key === name)!;
  assert.deepEqual(key("tickets").readers, [{ node: "loop:each_ticket", field: null, how: "over", source: null }]);
  assert.deepEqual(key("ticket").producers, ["loop:each_ticket"]);
  assert.deepEqual(key("ticket").readers.map((r) => r.node), ["step:classify", "step:draft", "step:escalate"]);
  // Three steps produce `reply`, on different paths; the For collects it into `replies`.
  assert.deepEqual(key("reply").producers, ["step:draft", "step:escalate", "step:fix"]);
  assert.ok(key("reply").readers.some((r) => r.node === "loop:each_ticket" && r.how === "collects"));
  assert.deepEqual(key("replies").producers, ["loop:each_ticket"]);
  assert.deepEqual(key("passed").readers, [{ node: "loop:revise", field: null, how: "until", source: null }]);
  assert.equal(key("classification").readers[0].source, "measured");

  const edges = dataEdges(keys);
  assert.deepEqual(edges.find((e) => e.from === "step:start" && e.to === "loop:each_ticket")?.keys, ["tickets"]);
  assert.deepEqual(edges.find((e) => e.from === "loop:each_ticket" && e.to === "step:draft")?.keys, ["ticket"]);
  assert.deepEqual(edges.find((e) => e.from === "step:start" && e.to === "step:draft")?.keys, ["policy"]);
});

test("a run's path: a route's entry says which arrow it took", () => {
  const g = stepGraphOf(graph("billing-support"));
  const path = pathOf(g, run("fired"));
  assert.deepEqual([...path.visited].sort(), ["step:by_tone", "step:end", "step:escalate", "step:start", "step:triage"]);
  assert.deepEqual([...path.taken], [
    ["step:start->step:triage", 1], ["step:triage->step:by_tone", 1], ["step:by_tone->step:escalate", 1], ["step:escalate->step:end", 1],
  ]);
  assert.deepEqual([path.waiting, path.failed], [null, null]);
});

test("a run's path through a loop: each pass counts, and an Until that held mid-body ends the pass there", () => {
  const g = stepGraphOf(graph("fixed-policy"));
  const path = pathOf(g, run("loop"));
  // Two passes: check and summarize_check ran twice, fix once (the second pass held at summarize_check).
  assert.equal(path.taken.get("loop:revise->step:check"), 2);
  assert.equal(path.taken.get("step:check->step:summarize_check"), 2);
  assert.equal(path.taken.get("step:summarize_check->step:fix"), 1);
  assert.equal(path.taken.get("step:fix->loop:revise"), 1);
  assert.equal(path.taken.get("step:draft->loop:revise"), 1);
  assert.equal(path.taken.get("loop:revise->step:end"), 1);
  assert.ok(path.visited.has("loop:revise") && path.visited.has("step:end"));
});

test("a run that failed at a loop's cap stops at the loop and does not leave it", () => {
  const g = stepGraphOf(graph("fixed-policy"));
  const path = pathOf(g, run("capped"));
  assert.equal(path.failed, "loop:revise");
  assert.equal(path.taken.get("step:fix->loop:revise"), 3);
  assert.equal(path.taken.get("loop:revise->step:end"), undefined);
  assert.ok(!path.visited.has("step:end"));
});

test("a paused run waits at a step it has not recorded yet, inside the loops around it", () => {
  const g = stepGraphOf(graph("fixed-policy"));
  const whole = run("loop");
  const paused = { ...whole, status: "paused" as const, position: "step:fix", history: whole.history.slice(0, 4),
                   pause: { kind: "task", step: "fix", tasks: [] }, error: null };
  const path = pathOf(g, paused);
  assert.equal(path.waiting, "step:fix");
  assert.ok(path.visited.has("step:fix") && path.visited.has("loop:revise"));
  assert.equal(path.taken.get("step:summarize_check->step:fix"), 1);
  assert.equal(path.taken.get("step:fix->loop:revise"), undefined);
});

test("traffic: runs per arrow and per step, a run counted once however many passes it made", () => {
  const g = stepGraphOf(graph("fixed-policy"));
  const traffic = emptyTraffic();
  fold(traffic, g, run("loop"));
  fold(traffic, g, run("capped"));
  assert.equal(traffic.runs, 2);
  assert.deepEqual(traffic.byStatus, { done: 1, failed: 1 });
  assert.equal(traffic.edges.get("step:check->step:summarize_check"), 2);
  assert.equal(traffic.edges.get("loop:revise->step:end"), 1);
  assert.equal(traffic.nodes.get("step:fix"), 2);
  assert.equal(traffic.nodes.get("step:end"), 1);
  assert.equal(traffic.failed.get("loop:revise"), 1);
});
