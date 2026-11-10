'use strict';
// The graph preview: the page, the state posted after each check, and the preview itself rendered
// on the server (src/webview/Preview.tsx with the console's card canvas, bundled here by esbuild as
// dist/preview.js is) over what the real compiler prints. The plan's E2 proof is the last test:
// editing a Next_Step in billing-support redraws the edge, compile and render within a second.

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

let render; // (state, direction) => HTML

before(async () => {
  const { build } = await import('esbuild');
  const { oneReact } = await import('../one-react.mjs');
  const out = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'aip-preview-')), 'render.cjs');
  await build({
    stdin: {
      contents: `
        import { renderToString } from "react-dom/server";
        import { Preview } from "./Preview.tsx";
        export const render = (state, direction = "down") =>
          renderToString(<Preview state={state} direction={direction} onDirection={() => {}} onOpen={() => {}} />);`,
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

/** The wires the canvas drew, as `from -> to` with step names. */
function wires(html) {
  return [...html.matchAll(/<path[^>]*class="aipc-wire[^"]*"[^>]*data-from="([^"]+)" data-to="([^"]+)"/g)].map((m) => `${m[1]} -> ${m[2]}`);
}

const cards = (html) => [...html.matchAll(/data-testid="canvas-card" data-step="([^"]+)"/g)].map((m) => m[1]);

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
  assert.match(fs.readFileSync(path.join(ROOT, 'dist', 'preview.css'), 'utf8'), /\.aipc-card/, 'the canvas styles are in the bundle');
});

test('a procedure.aip is named by its folder', () => {
  assert.equal(titleOf('/a/billing-support/procedure.aip'), 'billing-support');
  assert.equal(titleOf('/a/draft.aip'), 'draft.aip');
});

test('a clean check draws its graph; an error keeps the last graph that compiled', async () => {
  const source = fs.readFileSync(BILLING, 'utf8');
  const clean = previewState({ result: await check({ command: AIP, file: BILLING, source }), file: BILLING, source });
  assert.equal(clean.title, 'billing_support');
  assert.equal(clean.stale, false);
  assert.deepEqual(clean.problems, []);
  assert.ok(clean.graph.nodes.length > 0);

  const broken = source.replace('Next_Step by_tone', 'Next_Step by_tonne');
  const kept = previewState({ result: await check({ command: AIP, file: BILLING, source: broken }), file: BILLING, source: broken, previous: clean });
  assert.equal(kept.graph, clean.graph);
  assert.equal(kept.source, source, 'the open card\'s slice is from the text the graph came from');
  assert.equal(kept.stale, true);
  assert.ok(kept.problems.some((p) => p.severity === 'error' && typeof p.line === 'number'));
  const html = render(kept);
  assert.match(html, /showing the last graph that compiled/);
  assert.match(html, /data-testid="preview-problem"/);
  assert.ok(cards(html).includes('by_tone'));

  const first = previewState({ result: await check({ command: AIP, file: BILLING, source: broken }), file: BILLING, source: broken });
  assert.equal(first.graph, null);
  assert.equal(first.title, 'billing-support');
  assert.match(render(first), /has not compiled yet/);

  const missing = previewState({ result: { status: 'not-found', error: 'x' }, file: BILLING, source, previous: clean });
  assert.match(missing.status, /aip not found/);
  assert.equal(missing.graph, clean.graph);
});

test('the preview draws one card per step, a frame per loop, both directions', async () => {
  const file = path.join(ROOT, '..', '..', 'examples', 'language', 'ticket-triage', 'procedure.aip');
  const source = fs.readFileSync(file, 'utf8');
  const state = previewState({ result: await check({ command: AIP, file, source }), file, source });
  const steps = state.graph.nodes.filter((n) => n.labels.includes('Step')).map((n) => n.properties.name);
  for (const direction of ['down', 'right']) {
    const html = render(state, direction);
    assert.match(html, new RegExp(`data-direction="${direction}"`));
    assert.deepEqual(new Set(cards(html)), new Set(steps));
    assert.match(html, /data-testid="canvas-frame"/);
    assert.match(html, /<button type="button" aria-pressed="true">/);
  }
});

test('editing a Next_Step redraws the edge within a second (plan E2)', async () => {
  const source = fs.readFileSync(BILLING, 'utf8');
  const before = render(previewState({ result: await check({ command: AIP, file: BILLING, source }), file: BILLING, source }));
  assert.ok(wires(before).includes('escalate -> end'), wires(before).join(', '));
  assert.ok(!wires(before).includes('escalate -> reply'));

  // escalate's `Next_Step end` becomes `Next_Step reply`, which still compiles clean.
  const at = source.indexOf('Next_Step end');
  assert.ok(at > source.indexOf('Execute escalate') && at < source.indexOf('Task_Agent With reply'));
  const edited = `${source.slice(0, at)}Next_Step reply${source.slice(at + 'Next_Step end'.length)}`;
  const started = performance.now();
  const state = previewState({ result: await check({ command: AIP, file: BILLING, source: edited }), file: BILLING, source: edited });
  const after = render(state);
  const ms = performance.now() - started;
  assert.deepEqual(state.problems, []);
  assert.ok(wires(after).includes('escalate -> reply'), wires(after).join(', '));
  assert.ok(!wires(after).includes('escalate -> end'));
  assert.match(after, /data-port="next" data-kind="next" data-target="reply"/);
  // The editor waits aip.debounceMs (300 by default) after the last keystroke, then this.
  console.log(`# compile and redraw after the edit: ${Math.round(ms)} ms, plus the 300 ms debounce`);
  assert.ok(ms + 300 < 1000, `compile and redraw took ${Math.round(ms)} ms after the 300 ms debounce`);
});
