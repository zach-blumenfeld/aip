'use strict';
// The graph preview: the page, the state posted after each check, and the preview itself rendered
// on the server (src/webview/Preview.tsx with the console's step graph, bundled here by esbuild as
// dist/preview.js is) over what the real compiler prints. The plan's E3 proof is the ticket-triage
// test: the loop is a node with its body beside it. E2's is the last: editing a Next_Step in
// billing-support redraws the arrow, compile and render within a second.

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { test, before } = require('node:test');
const assert = require('node:assert/strict');

const { check } = require('../src/compiler');
const { previewHtml, previewState, titleOf } = require('../src/preview');

const AIP = process.env.AIP_COMMAND || 'uv run aip';
const ROOT = path.join(__dirname, '..');
const BILLING = path.join(ROOT, '..', '..', 'examples', 'language', 'billing-support', 'procedure.aip');

let render; // (state, direction, mode) => HTML

before(async () => {
  const { build } = await import('esbuild');
  const { oneReact } = await import('../one-react.mjs');
  const out = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'aip-preview-')), 'render.cjs');
  await build({
    stdin: {
      contents: `
        import { renderToString } from "react-dom/server";
        import { Preview } from "./Preview.tsx";
        export const render = (state, direction = "down", mode = "control") =>
          renderToString(<Preview state={state} direction={direction} mode={mode} onDirection={() => {}} onMode={() => {}} onOpen={() => {}} />);`,
      resolveDir: path.join(ROOT, 'src', 'webview'),
      loader: 'tsx',
    },
    outfile: out,
    bundle: true,
    platform: 'node',
    format: 'cjs',
    jsx: 'automatic',
    loader: { '.css': 'empty' },
    define: { 'process.env.NODE_ENV': '"production"' },
    plugins: [oneReact],
    logLevel: 'silent',
  });
  ({ render } = require(out));
});

/** The arrows the step graph drew, as `from -> to` with step and loop names. */
function edges(html) {
  return [...html.matchAll(/data-testid="step-edge" data-from="([^"]+)" data-to="([^"]+)"/g)].map((m) => `${m[1]} -> ${m[2]}`);
}

/** Every node the step graph drew, by name: where it sits, and whether it is a loop. */
function nodes(html) {
  const out = {};
  for (const m of html.matchAll(/transform="translate\(([-\d.]+), ([-\d.]+)\)" data-testid="(step|loop)-node" data-(?:step|loop)="([^"]+)"/g)) {
    out[m[4]] = { x: Number(m[1]), y: Number(m[2]), loop: m[3] === 'loop' };
  }
  return out;
}

const steps = (html) => Object.entries(nodes(html)).filter(([, n]) => !n.loop).map(([name]) => name);

test('the page loads the bundles under a nonce and nothing else', () => {
  const html = previewHtml({ scriptUri: 'vscode-resource:/dist/preview.js', styleUri: 'vscode-resource:/dist/preview.css',
    cspSource: 'vscode-resource:', title: 'Graph: <x>', nonce: 'abc123' });
  assert.match(html, /script-src 'nonce-abc123'/);
  assert.match(html, /<script nonce="abc123" src="vscode-resource:\/dist\/preview.js"><\/script>/);
  assert.match(html, /<link rel="stylesheet" href="vscode-resource:\/dist\/preview.css">/);
  assert.match(html, /<title>Graph: &lt;x&gt;<\/title>/);
  assert.match(html, /default-src 'none'/);
});

test('the build wrote the preview bundles', () => {
  for (const file of ['preview.js', 'preview.css']) {
    const stat = fs.statSync(path.join(ROOT, 'dist', file));
    assert.ok(stat.size > 0, `dist/${file} is empty; run npm run build`);
  }
  const css = fs.readFileSync(path.join(ROOT, 'dist', 'preview.css'), 'utf8');
  assert.match(css, /\.step-graph/, 'the step graph\'s styles are in the bundle');
  assert.doesNotMatch(css, /\.aipc-card/, 'the card canvas has left the extension');
});

test('a procedure.aip is named by its folder', () => {
  assert.equal(titleOf('/a/billing-support/procedure.aip'), 'billing-support');
  assert.equal(titleOf('/a/draft.aip'), 'draft.aip');
});

test('a clean check draws its graph; an error keeps the last graph that compiled', async () => {
  const source = fs.readFileSync(BILLING, 'utf8');
  const clean = previewState({ result: await check({ command: AIP, file: BILLING, source }), file: BILLING });
  assert.equal(clean.title, 'billing_support');
  assert.equal(clean.stale, false);
  assert.deepEqual(clean.problems, []);
  assert.ok(clean.graph.nodes.length > 0);

  const broken = source.replace('Next_Step by_tone', 'Next_Step by_tonne');
  const kept = previewState({ result: await check({ command: AIP, file: BILLING, source: broken }), file: BILLING, previous: clean });
  assert.equal(kept.graph, clean.graph);
  assert.equal(kept.stale, true);
  assert.ok(kept.problems.some((p) => p.severity === 'error' && typeof p.line === 'number'));
  const html = render(kept);
  assert.match(html, /showing the last graph that compiled/);
  assert.match(html, /data-testid="preview-problem"/);
  assert.ok(steps(html).includes('by_tone'));

  const first = previewState({ result: await check({ command: AIP, file: BILLING, source: broken }), file: BILLING });
  assert.equal(first.graph, null);
  assert.equal(first.title, 'billing-support');
  assert.match(render(first), /has not compiled yet/);

  const missing = previewState({ result: { status: 'not-found', error: 'x' }, file: BILLING, previous: clean });
  assert.match(missing.status, /aip not found/);
  assert.equal(missing.graph, clean.graph);
});

test('the preview draws the step graph: a loop is a node with its body beside it, both directions (plan E3)', async () => {
  const file = path.join(ROOT, '..', '..', 'examples', 'language', 'ticket-triage', 'procedure.aip');
  const source = fs.readFileSync(file, 'utf8');
  const state = previewState({ result: await check({ command: AIP, file, source }), file });
  const names = state.graph.nodes.filter((n) => n.labels.includes('Step')).map((n) => n.properties.name);
  for (const direction of ['down', 'right']) {
    const html = render(state, direction);
    assert.match(html, new RegExp(`data-testid="step-graph" data-direction="${direction}" data-mode="control"`));
    assert.doesNotMatch(html, /canvas-card/, 'no cards');
    assert.deepEqual(new Set(steps(html)), new Set(names));
    const drawn = nodes(html);
    assert.ok(drawn.each_ticket && drawn.each_ticket.loop, 'each_ticket is a loop node');
    assert.ok(drawn.revise && drawn.revise.loop, 'revise is a loop node');
    // The body hangs beside its loop, as the console draws it: to the right when the graph runs down,
    // below when it runs right; the loop's exit carries on past it along the loop's own axis.
    const [loop, body, after] = [drawn.each_ticket, drawn.classify, drawn.summarize];
    if (direction === 'down') {
      assert.ok(body.x > loop.x, `classify (x ${body.x}) beside each_ticket (x ${loop.x})`);
      assert.ok(after.y > loop.y && after.x >= loop.x && after.x < body.x, 'summarize below each_ticket, in its column');
      assert.ok(drawn.check.x > drawn.revise.x, 'check hangs beside revise');
    } else {
      assert.ok(body.y > loop.y, `classify (y ${body.y}) beside each_ticket (y ${loop.y})`);
      assert.ok(after.x > loop.x && after.y >= loop.y && after.y < body.y, 'summarize right of each_ticket, in its row');
      assert.ok(drawn.check.y > drawn.revise.y, 'check hangs beside revise');
    }
    const arrows = edges(html);
    for (const arrow of ['each_ticket -> classify', 'escalate -> each_ticket', 'revise -> check', 'fix -> revise', 'each_ticket -> summarize']) {
      assert.ok(arrows.includes(arrow), `${arrow} in ${arrows.join(', ')}`);
    }
    assert.match(html, /<button type="button" aria-pressed="true">control flow<\/button>/);
    assert.match(html, new RegExp(`<button type="button" aria-pressed="true">${direction}</button>`));
  }
});

test('data flow is a toggle: the same graph, faint, with a key to pick', async () => {
  const file = path.join(ROOT, '..', '..', 'examples', 'language', 'ticket-triage', 'procedure.aip');
  const source = fs.readFileSync(file, 'utf8');
  const state = previewState({ result: await check({ command: AIP, file, source }), file });
  const html = render(state, 'down', 'data');
  assert.match(html, /data-testid="step-graph" data-direction="down" data-mode="data"/);
  assert.match(html, /<button type="button" aria-pressed="true">data flow<\/button>/);
  assert.match(html, /data-testid="preview-keys"/);
  for (const key of ['tickets', 'classification', 'reply', 'replies', 'summary']) assert.match(html, new RegExp(`<code>${key}</code>`));
  // Nothing is picked yet, so no data arrow is drawn; the control edges stay under them.
  assert.doesNotMatch(html, /data-testid="data-edge"/);
  assert.ok(edges(html).length > 0);
  assert.doesNotMatch(render(state, 'down', 'control'), /data-testid="preview-keys"/);
});

test('editing a Next_Step redraws the arrow within a second (plans E2, E3)', async () => {
  const source = fs.readFileSync(BILLING, 'utf8');
  const before = render(previewState({ result: await check({ command: AIP, file: BILLING, source }), file: BILLING }));
  assert.ok(edges(before).includes('escalate -> end'), edges(before).join(', '));
  assert.ok(!edges(before).includes('escalate -> reply'));

  // escalate's `Next_Step end` becomes `Next_Step reply`, which still compiles clean.
  const at = source.indexOf('Next_Step end');
  assert.ok(at > source.indexOf('Execute escalate') && at < source.indexOf('Task_Agent With reply'));
  const edited = `${source.slice(0, at)}Next_Step reply${source.slice(at + 'Next_Step end'.length)}`;
  const started = performance.now();
  const state = previewState({ result: await check({ command: AIP, file: BILLING, source: edited }), file: BILLING });
  const after = render(state);
  const ms = performance.now() - started;
  assert.deepEqual(state.problems, []);
  assert.ok(edges(after).includes('escalate -> reply'), edges(after).join(', '));
  assert.ok(!edges(after).includes('escalate -> end'));
  assert.match(after, /data-testid="step-edge" data-from="escalate" data-to="reply" data-kinds="next"/);
  // The editor waits aip.debounceMs (300 by default) after the last keystroke, then this.
  console.log(`# compile and redraw after the edit: ${Math.round(ms)} ms, plus the 300 ms debounce`);
  assert.ok(ms + 300 < 1000, `compile and redraw took ${Math.round(ms)} ms after the 300 ms debounce`);
});
