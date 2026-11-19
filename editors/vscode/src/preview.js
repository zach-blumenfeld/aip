'use strict';
/**
 * The graph preview's side in the extension host, with no `vscode` import so node tests it: the
 * webview's page, and the state posted to it after every check of the document (what
 * src/webview/Preview.tsx draws). While the buffer has errors the compiler prints no graph, so the
 * state keeps the last graph that compiled and says it is stale.
 */

const path = require('node:path');

/** A random token for the page's Content-Security-Policy. */
function nonce() {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  let text = '';
  for (let i = 0; i < 32; i++) text += chars.charAt(Math.floor(Math.random() * chars.length));
  return text;
}

const escapeHtml = (text) => String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

/** The webview's HTML: dist/preview.css and dist/preview.js (as webview URIs), nothing else. */
function previewHtml({ scriptUri, styleUri, cspSource, title, nonce: token = nonce() }) {
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${cspSource} 'unsafe-inline'; script-src 'nonce-${token}'; img-src ${cspSource} data:;">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="stylesheet" href="${escapeHtml(styleUri)}">
<title>${escapeHtml(title)}</title>
</head>
<body>
<div id="root"></div>
<script nonce="${token}" src="${escapeHtml(scriptUri)}"></script>
</body>
</html>`;
}

/** The preview's title for a file: `procedure.aip` is named by its folder. */
function titleOf(file) {
  const base = path.basename(file);
  return base === 'procedure.aip' ? path.basename(path.dirname(file)) : base;
}

/**
 * The state to post after a check. `result` is what compiler.check resolved to, `previous` the
 * state posted last (or undefined).
 */
function previewState({ result, file, previous }) {
  const kept = previous && previous.graph ? { graph: previous.graph, title: previous.title } : null;
  if (!result || result.status !== 'report') {
    const status = result && result.status === 'not-found'
      ? 'aip not found: the preview needs the compiler (see the status bar)'
      : `the compiler did not answer${result && result.error ? `: ${result.error}` : ''}`;
    return { title: kept ? kept.title : titleOf(file), graph: kept ? kept.graph : null,
      problems: [], stale: Boolean(kept), status };
  }
  const { report } = result;
  const problems = (report.diagnostics || []).map((d) => ({
    severity: d.severity, message: d.message, line: typeof d.line === 'number' ? d.line : null, code: d.code,
  }));
  if (report.graph && Array.isArray(report.graph.nodes)) {
    return { title: report.procedure || titleOf(file), graph: report.graph, problems, stale: false };
  }
  return { title: kept ? kept.title : titleOf(file), graph: kept ? kept.graph : null,
    problems, stale: Boolean(kept) };
}

module.exports = { previewHtml, previewState, titleOf, nonce };
