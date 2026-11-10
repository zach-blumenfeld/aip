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

test("steps are nodes and the control edges are the arrows", () => {
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

test("a loop is a node: ENTERS into its body, Continue back to it, and its exit; nothing else goes back", () => {
  const g = stepGraphOf(graph("ticket-triage"));
  const edge = (from: string, to: string) => g.edges.find((e) => e.from === from && e.to === to);
  assert.deepEqual(g.nodes["loop:each_ticket"].children, ["step:classify", "step:by_tone", "step:draft", "step:escalate", "loop:revise"]);
  assert.deepEqual(g.nodes["loop:revise"].children, ["step:check", "step:fix"]);
  assert.equal(g.nodes["loop:each_ticket"].loop, true);
  assert.equal(g.nodes["step:classify"].loop, false);
  assert.equal(g.nodes["loop:revise"].parent, "loop:each_ticket");
  assert.equal(g.nodes["loop:revise"].title, "Until passed, At_Most 4, Else_Fail");
  // The node's one line: what it runs over or until, and its cap. The rest stays in the header.
  assert.equal(g.nodes["loop:revise"].summary, "Until passed, At_Most 4");
  assert.equal(g.nodes["loop:each_ticket"].summary, "Over tickets, At_Most 50");
  assert.equal(stepGraphOf(graph("fixed-policy")).nodes["loop:revise"].summary, "Until check_summary.all_hold, At_Most 3");

  assert.equal(edge("loop:each_ticket", "step:classify")?.enter, true);
  assert.equal(edge("loop:revise", "step:check")?.enter, true);
  // The pass is over: from a step, and from the inner loop's exit line.
  assert.deepEqual([edge("step:escalate", "loop:each_ticket")?.toLoop, edgeLabel(edge("step:escalate", "loop:each_ticket")!)], [true, "continue"]);
  assert.equal(edge("loop:revise", "loop:each_ticket")?.toLoop, true);
  // Every cycle is a loop node: the fix goes back to its loop, never to the check, and the only
  // arrows that lead to a node that has already run are the Continues.
  assert.deepEqual([edge("step:fix", "loop:revise")?.toLoop, edgeLabel(edge("step:fix", "loop:revise")!)], [true, "continue"]);
  assert.equal(edge("step:fix", "step:check"), undefined);
  assert.equal(edgeLabel(edge("step:check", "step:fix")!), "");
  assert.deepEqual(g.edges.filter((e) => e.toLoop).map((e) => e.key).sort(),
                   ["loop:revise->loop:each_ticket", "step:escalate->loop:each_ticket", "step:fix->loop:revise"]);
  // A step into a loop, and a loop's exit, are arrows to and from the loop node.
  assert.equal(edge("step:draft", "loop:revise")?.toLoop, false);
  assert.ok(edge("loop:each_ticket", "step:summarize"));
  assert.equal(edgeLabel(edge("step:by_tone", "step:escalate")!), "< 0.6 · angry");
  // Membership draws nothing: no arrow from a loop to a step of its body but the way in.
  assert.equal(g.edges.filter((e) => e.from === "loop:each_ticket").length, 2);
});

const within = (inner: Box, outer: Box) =>
  inner.x >= outer.x && inner.y >= outer.y && inner.x + inner.w <= outer.x + outer.w && inner.y + inner.h <= outer.y + outer.h;
const apart = (a: Box, b: Box) => a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y;
/** The layout in its own terms: `o` across (x top-down, y left-to-right), `r` along the flow. */
const along = (box: Box, direction: Direction) => (direction === "down" ? { o: box.x, so: box.w, r: box.y, sr: box.h } : { o: box.y, so: box.h, r: box.x, sr: box.w });

test("the layout, down and right: a body beside its loop node, nothing overlapping, every arrow in the picture", () => {
  for (const name of [...EXAMPLES, "dynamic-policy"]) for (const direction of DIRECTIONS) {
    const g = stepGraphOf(graph(name));
    const layout = layoutOf(g, direction);
    const where = `${name} ${direction}`;
    const ids = Object.keys(g.nodes);
    const inside = (id: string, loop: string) => { for (let p = g.nodes[id].parent; p !== null; p = g.nodes[p].parent) if (p === loop) return true; return false; };
    for (const id of ids) {
      const box = layout.boxes[id];
      assert.ok(box, `${where}: ${id} has a box`);
      assert.ok(box.x >= 0 && box.y >= 0 && box.x + box.w <= layout.width && box.y + box.h <= layout.height, `${where}: ${id} is in the picture`);
      if (!g.nodes[id].loop) assert.deepEqual([box.w, box.h], [SIZE.nodeWidth, SIZE.nodeHeight]);
      else assert.ok(box.h === SIZE.loopHeight && box.w >= SIZE.nodeWidth && box.w <= SIZE.loopWidest, `${where}: ${id} is a loop node`);
    }
    // No node overlaps another: there are no frames.
    for (const a of ids) for (const b of ids) if (a < b) assert.ok(apart(layout.boxes[a], layout.boxes[b]), `${where}: ${a} and ${b} do not overlap`);

    for (const loop of ids.filter((id) => g.nodes[id].loop)) {
      const node = along(layout.boxes[loop], direction);
      // The whole body is off to the loop node's far side, and starts level with it.
      for (const id of ids.filter((x) => inside(x, loop))) {
        const b = along(layout.boxes[id], direction);
        assert.ok(b.o >= node.o + node.so + SIZE.rail, `${where}: ${id} is beside ${loop}`);
        assert.ok(b.r >= node.r, `${where}: ${id} is not before ${loop}`);
      }
      const first = along(layout.boxes[g.nodes[loop].children[0]], direction);
      assert.ok(first.r < node.r + node.sr && first.r + first.sr > node.r, `${where}: the body of ${loop} starts beside it`);
      // The step after the loop is past the whole body, on the loop node's own axis.
      const exit = g.edges.find((e) => e.from === loop && !e.enter && !e.toLoop);
      if (exit) {
        const after = along(layout.boxes[exit.to], direction);
        for (const id of ids.filter((x) => inside(x, loop))) {
          const b = along(layout.boxes[id], direction);
          assert.ok(after.r >= b.r + b.sr, `${where}: ${exit.to} is past ${id}`);
        }
        assert.equal(after.o + after.so / 2, node.o + node.so / 2, `${where}: ${exit.to} is straight on from ${loop}`);
      }
    }

    assert.equal(layout.edges.length, g.edges.length, `${where}: every arrow is drawn`);
    for (const e of layout.edges) {
      for (const [x, y] of e.points) assert.ok(x >= 0 && y >= 0 && x <= layout.width && y <= layout.height, `${where}: ${e.edge.key} is in the picture`);
      // Arrows run along the axes or straight from box to box; a rail never cuts through a node.
      if (!e.rail && !e.edge.enter) continue;
      for (let i = 1; i < e.points.length; i++) {
        const [x0, y0] = e.points[i - 1], [x1, y1] = e.points[i];
        assert.ok(x0 === x1 || y0 === y1, `${where}: ${e.edge.key} runs square`);
        for (const id of ids) {
          const b = layout.boxes[id];
          const through = Math.max(x0, x1) > b.x && Math.min(x0, x1) < b.x + b.w && Math.max(y0, y1) > b.y && Math.min(y0, y1) < b.y + b.h;
          assert.ok(!through, `${where}: ${e.edge.key} does not cross ${id}`);
        }
      }
    }
    // An arrow's label is not on a node.
    for (const e of layout.edges) {
      const text = edgeLabel(e.edge);
      if (!text) continue;
      const w = 6 * text.length, [x, y] = e.label;
      const label = { x: e.anchor === "start" ? x : e.anchor === "end" ? x - w : x - w / 2, y: y - 6, w, h: 12 };
      for (const id of ids) assert.ok(apart(label, layout.boxes[id]), `${where}: the label of ${e.edge.key} is clear of ${id}`);
    }
    // The flow runs the way it is drawn: a step is past the one before it.
    const start = layout.boxes["step:start"], end = layout.boxes["step:end"];
    if (direction === "down") assert.ok(end.y > start.y + start.h, where); else assert.ok(end.x > start.x + start.w, where);
  }
});

test("the layout: a loop reads as a cycle, in beside the loop node and back along a rail in the gutter", () => {
  const g = stepGraphOf(graph("ticket-triage"));
  const layout = layoutOf(g, "down");
  const placed = (key: string) => layout.edges.find((e) => e.edge.key === key)!;
  const loop = layout.boxes["loop:each_ticket"], first = layout.boxes["step:classify"];

  const next = placed("step:classify->step:by_tone");
  assert.equal(next.rail, false);
  assert.equal(next.points.length, 2);
  assert.equal(next.points[0][1], first.y + SIZE.nodeHeight);
  assert.equal(next.points[1][1], layout.boxes["step:by_tone"].y);

  // ENTERS: straight across from the loop node's side to the first step of the body.
  const enter = placed("loop:each_ticket->step:classify");
  assert.deepEqual(enter.points, [[loop.x + loop.w, enter.points[0][1]], [first.x, enter.points[0][1]]]);

  // Continue: out of the step, up a rail between the loop node and the body, into the loop node's side under the way in.
  const over = placed("step:escalate->loop:each_ticket");
  assert.equal(over.rail, true);
  const last = over.points[over.points.length - 1], rail = over.points[over.points.length - 2];
  assert.equal(last[0], loop.x + loop.w);
  assert.ok(last[1] > enter.points[0][1] && last[1] < loop.y + loop.h);
  assert.ok(rail[0] > loop.x + loop.w && rail[0] < first.x);
  // The inner loop's exit is the outer loop's Continue: its rail is further from the body, and arrives lower.
  const inner = placed("loop:revise->loop:each_ticket");
  assert.ok(inner.points[inner.points.length - 2][0] < rail[0]);
  assert.ok(inner.points[inner.points.length - 1][1] > last[1]);

  // The exit carries straight on from the loop node, past the body.
  const exit = placed("loop:each_ticket->step:summarize");
  assert.equal(exit.points.length, 2);
  assert.equal(exit.points[0][0], exit.points[1][0]);
  assert.deepEqual(exit.points[0], [loop.x + loop.w / 2, loop.y + loop.h]);

  // The inner loop is a cycle of its own: `check` and `fix` beside the loop node, and `fix` back to it along a rail.
  const revise = layout.boxes["loop:revise"], check = layout.boxes["step:check"];
  assert.ok(check.x > revise.x + revise.w && layout.boxes["step:fix"].y > check.y);
  const back = placed("step:fix->loop:revise");
  assert.equal(back.rail, true);
  assert.equal(back.points[back.points.length - 1][0], revise.x + revise.w);
  // Nothing goes back but a Continue.
  assert.deepEqual(layout.edges.filter((e) => e.rail).map((e) => e.edge.toLoop), [true, true, true]);
});

test("the layout: a For inside a Loop is a cycle hung off the outer loop's body", () => {
  const g = stepGraphOf(graph("dynamic-policy"));
  const layout = layoutOf(g, "down");
  const outer = layout.boxes["loop:revise"], inner = layout.boxes["loop:review"], check = layout.boxes["step:check"];
  assert.ok(inner.x > outer.x + outer.w && check.x > inner.x + inner.w);
  // The one-step body goes straight back, under the way in.
  const back = layout.edges.find((e) => e.edge.key === "step:check->loop:review")!;
  assert.deepEqual(back.points.map((p) => p[0]), [check.x, inner.x + inner.w]);
  assert.equal(back.points[0][1], back.points[1][1]);
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
