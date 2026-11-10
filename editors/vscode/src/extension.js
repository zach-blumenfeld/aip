'use strict';
/**
 * The extension's activation: on open, on every change (debounced) and on save, run the compiler
 * on the buffer's text and publish its diagnostics as squiggles; a status-bar item shows the
 * compiler's version, or "aip not found" with the install hint. The same check feeds the graph
 * preview, a webview beside the editor drawing the console's card canvas (dist/preview.js), where
 * clicking a card jumps to its step. The commands compile, run and publish the procedure in the
 * integrated terminal and import one from the catalog with `aip get`. The work is in compiler.js,
 * preview.js and terminal.js; this file only talks to the `vscode` module.
 */

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vscode = require('vscode');
const compiler = require('./compiler');
const preview = require('./preview');
const terminal = require('./terminal');

const SEVERITY = {
  error: vscode.DiagnosticSeverity.Error,
  warning: vscode.DiagnosticSeverity.Warning,
  info: vscode.DiagnosticSeverity.Information,
};

function settings() {
  const configuration = vscode.workspace.getConfiguration('aip');
  return {
    command: configuration.get('command', 'aip') || 'aip',
    debounceMs: configuration.get('debounceMs', 300),
  };
}

function isProcedure(document) {
  return document.languageId === 'aip' && document.uri.scheme === 'file';
}

function activate(context) {
  const collection = vscode.languages.createDiagnosticCollection('aip');
  const output = vscode.window.createOutputChannel('AIP');
  const status = vscode.window.createStatusBarItem('aip.version', vscode.StatusBarAlignment.Right, 50);
  status.name = 'AIP';
  status.command = 'aip.showVersion';
  context.subscriptions.push(collection, output, status);

  let known = { status: 'unknown' }; // the last answer of `aip --version`
  const scheduled = new Map(); // document uri → its debounced check
  const previews = new Map(); // document uri → {panel, state, column}, the graph preview open on it
  let shell = null; // the AIP terminal the commands type into

  function paintStatus() {
    status.backgroundColor = undefined;
    if (known.status === 'version' && known.language !== null) {
      status.text = `$(check) aip ${known.aip}`;
      status.tooltip = `${known.line}\nChecks procedure.aip on every change.`;
    } else if (known.status === 'version') {
      status.text = `$(warning) aip ${known.aip}`;
      status.tooltip = `${known.line}\nThis aip runs the 0.8 format; the procedure language needs aip 0.9 or later.`;
      status.backgroundColor = new vscode.ThemeColor('statusBarItem.warningBackground');
    } else if (known.status === 'not-found') {
      status.text = '$(warning) aip not found';
      status.tooltip = compiler.INSTALL_HINT;
      status.backgroundColor = new vscode.ThemeColor('statusBarItem.warningBackground');
    } else if (known.status === 'failed') {
      status.text = '$(error) aip';
      status.tooltip = known.error;
      status.backgroundColor = new vscode.ThemeColor('statusBarItem.errorBackground');
    } else {
      status.text = 'aip';
      status.tooltip = 'Reading the compiler\'s version';
    }
    status.show();
  }

  async function refreshVersion() {
    known = await compiler.version(settings());
    if (known.status === 'failed' && known.error) output.appendLine(`aip --version: ${known.error}`);
    paintStatus();
  }

  async function check(document) {
    if (!isProcedure(document)) return;
    const version = document.version;
    const source = document.getText();
    const result = await compiler.check({ ...settings(), file: document.fileName, source });
    if (document.isClosed || document.version !== version) return; // a later edit has its own check
    showInPreview(document, result, source);
    if (result.status === 'not-found') {
      known = result;
      paintStatus();
      collection.delete(document.uri);
      return;
    }
    if (result.status === 'failed') {
      output.appendLine(`${document.fileName}: ${result.error}`);
      if (result.stderr) output.appendLine(result.stderr.trimEnd());
      known = result;
      paintStatus();
      collection.delete(document.uri);
      return;
    }
    const diagnostics = compiler.toDiagnostics(result.report).map((d) => {
      const range = document.validateRange(new vscode.Range(
        d.range.start.line, d.range.start.character, d.range.end.line, d.range.end.character,
      ));
      const diagnostic = new vscode.Diagnostic(range, d.message, SEVERITY[d.severity] ?? vscode.DiagnosticSeverity.Information);
      diagnostic.source = 'aip';
      diagnostic.code = d.code;
      return diagnostic;
    });
    collection.set(document.uri, diagnostics);
    if (known.status !== 'version') refreshVersion();
  }

  function schedule(document) {
    if (!isProcedure(document)) return;
    const key = document.uri.toString();
    let debounced = scheduled.get(key);
    if (!debounced) {
      debounced = compiler.debounce((doc) => { check(doc); }, settings().debounceMs);
      scheduled.set(key, debounced);
    }
    debounced(document);
  }

  function forget(document) {
    const key = document.uri.toString();
    const debounced = scheduled.get(key);
    if (debounced) debounced.cancel();
    scheduled.delete(key);
    collection.delete(document.uri);
  }

  // The graph preview.

  function showInPreview(document, result, source) {
    const open = previews.get(document.uri.toString());
    if (!open) return;
    open.state = preview.previewState({ result, file: document.fileName, source, previous: open.state });
    open.panel.title = `Graph: ${open.state.title}`;
    open.panel.webview.postMessage({ type: 'state', state: open.state });
  }

  function openPreview() {
    const document = activeProcedure();
    if (!document) return;
    const key = document.uri.toString();
    const existing = previews.get(key);
    if (existing) {
      existing.panel.reveal(vscode.ViewColumn.Beside, true);
      return;
    }
    const dist = vscode.Uri.joinPath(context.extensionUri, 'dist');
    const title = `Graph: ${preview.titleOf(document.fileName)}`;
    const panel = vscode.window.createWebviewPanel('aip.preview', title,
      { viewColumn: vscode.ViewColumn.Beside, preserveFocus: true },
      { enableScripts: true, localResourceRoots: [dist], retainContextWhenHidden: true });
    panel.iconPath = {
      light: vscode.Uri.joinPath(context.extensionUri, 'icons', 'aip-light.svg'),
      dark: vscode.Uri.joinPath(context.extensionUri, 'icons', 'aip-dark.svg'),
    };
    const editor = vscode.window.activeTextEditor;
    const open = { panel, state: undefined, column: editor && editor.document === document ? editor.viewColumn : vscode.ViewColumn.One };
    previews.set(key, open);
    panel.webview.html = preview.previewHtml({
      scriptUri: panel.webview.asWebviewUri(vscode.Uri.joinPath(dist, 'preview.js')).toString(),
      styleUri: panel.webview.asWebviewUri(vscode.Uri.joinPath(dist, 'preview.css')).toString(),
      cspSource: panel.webview.cspSource,
      title,
    });
    panel.webview.onDidReceiveMessage((message) => {
      if (!message) return;
      if (message.type === 'ready') {
        if (open.state) panel.webview.postMessage({ type: 'state', state: open.state });
        else check(document);
      } else if (message.type === 'open' && typeof message.line === 'number') {
        jumpTo(document, message.line, open.column);
      }
    }, undefined, context.subscriptions);
    panel.onDidDispose(() => previews.delete(key), undefined, context.subscriptions);
  }

  /** Show `line` (1-based) of the document in its editor, the cursor at the line's first word. */
  async function jumpTo(document, line, column) {
    const shown = vscode.window.visibleTextEditors.find((e) => e.document === document);
    const editor = await vscode.window.showTextDocument(document, { viewColumn: shown ? shown.viewColumn : column });
    const index = Math.min(Math.max(0, line - 1), document.lineCount - 1);
    const at = new vscode.Position(index, document.lineAt(index).firstNonWhitespaceCharacterIndex);
    editor.selection = new vscode.Selection(at, at);
    editor.revealRange(new vscode.Range(at, at), vscode.TextEditorRevealType.InCenterIfOutsideViewport);
  }

  // The commands that run aip on the procedure.

  /** The procedure a command is about: the active editor's, or the one whose preview is active. */
  function activeProcedure() {
    const editor = vscode.window.activeTextEditor;
    if (editor && editor.document.languageId === 'aip') return editor.document;
    for (const [key, open] of previews) {
      if (open.panel.active) return vscode.workspace.textDocuments.find((d) => d.uri.toString() === key);
    }
    vscode.window.showWarningMessage('Open a procedure.aip first.');
    return undefined;
  }

  /** Type a line into the AIP terminal, from the procedure's folder. */
  function type(line, cwd) {
    if (!shell || shell.exitStatus !== undefined) shell = vscode.window.createTerminal({ name: 'AIP', cwd });
    shell.show(true);
    shell.sendText(line);
  }

  /** Save the procedure (the commands read its folder from disk) and give it with its folder. */
  async function saved() {
    const document = activeProcedure();
    if (!document) return undefined;
    if (document.isDirty && !(await document.save())) return undefined;
    return { document, folder: path.dirname(document.fileName) };
  }

  async function compileCommand() {
    const target = await saved();
    if (target) type(terminal.compileLine(settings().command, target.folder), target.folder);
  }

  async function publishCommand() {
    const target = await saved();
    if (target) type(terminal.publishLine(settings().command, target.folder), target.folder);
  }

  async function runCommand() {
    const target = await saved();
    if (!target) return;
    const { document, folder } = target;
    const open = previews.get(document.uri.toString());
    let graph = open && open.state ? open.state.graph : null;
    if (!graph) {
      const result = await compiler.check({ ...settings(), file: document.fileName, source: document.getText() });
      graph = result.status === 'report' ? result.report.graph : null;
    }
    const name = preview.titleOf(document.fileName);
    const inputs = await vscode.window.showInputBox({
      title: `Run ${name}`,
      prompt: 'The Start step\'s inputs, as JSON',
      value: JSON.stringify(terminal.inputsTemplate(graph)),
      validateInput: (text) => {
        try { JSON.parse(text); return null; } catch (error) { return `Not JSON: ${error.message}`; }
      },
    });
    if (inputs === undefined) return;
    const file = path.join(os.tmpdir(), `aip-inputs-${name}.json`);
    fs.writeFileSync(file, inputs);
    type(terminal.runLine(settings().command, folder, file), folder);
  }

  async function importCommand() {
    const ref = await vscode.window.showInputBox({
      title: 'Import a procedure from the catalog',
      prompt: 'A published name, or name@revision (`aip list` shows them)',
      validateInput: (text) => (text.trim() ? null : 'A name is needed'),
    });
    if (ref === undefined) return;
    const workspace = vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders[0];
    const picked = await vscode.window.showOpenDialog({
      canSelectFolders: true, canSelectFiles: false, canSelectMany: false,
      openLabel: 'Import here', title: 'Where to write the procedure\'s folder',
      defaultUri: workspace ? workspace.uri : undefined,
    });
    if (!picked || !picked.length) return;
    const parent = picked[0].fsPath;
    const out = terminal.importFolder(parent, ref);
    const result = await compiler.run(settings().command, ['get', ref.trim(), '--out', out], { cwd: parent });
    if (result.status === 'not-found') {
      vscode.window.showWarningMessage(compiler.INSTALL_HINT);
      return;
    }
    if (result.status !== 'exited' || result.code !== 0) {
      const said = ((result.stderr || '') + (result.stdout || '')).trim() || result.error || `exit ${result.code}`;
      output.appendLine(`aip get ${ref.trim()}: ${said}`);
      vscode.window.showErrorMessage(`aip get ${ref.trim()}: ${said.split('\n').pop()}`);
      return;
    }
    await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(path.join(out, 'procedure.aip')));
  }

  function checkAll() {
    for (const document of vscode.workspace.textDocuments) check(document);
  }

  async function showVersion() {
    if (known.status === 'not-found') {
      const choice = await vscode.window.showWarningMessage(compiler.INSTALL_HINT, 'Open settings');
      if (choice) vscode.commands.executeCommand('workbench.action.openSettings', 'aip.command');
    } else if (known.status === 'version') {
      vscode.window.showInformationMessage(known.line);
    } else if (known.status === 'failed') {
      vscode.window.showErrorMessage(`aip: ${known.error}`);
    } else {
      await refreshVersion();
    }
  }

  context.subscriptions.push(
    vscode.workspace.onDidOpenTextDocument(check),
    vscode.workspace.onDidChangeTextDocument((event) => schedule(event.document)),
    vscode.workspace.onDidSaveTextDocument(check),
    vscode.workspace.onDidCloseTextDocument(forget),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (!event.affectsConfiguration('aip')) return;
      for (const debounced of scheduled.values()) debounced.cancel();
      scheduled.clear();
      refreshVersion().then(checkAll);
    }),
    vscode.commands.registerCommand('aip.check', () => {
      const editor = vscode.window.activeTextEditor;
      if (editor) check(editor.document);
    }),
    vscode.commands.registerCommand('aip.showVersion', showVersion),
    vscode.commands.registerCommand('aip.openPreview', openPreview),
    vscode.commands.registerCommand('aip.compile', compileCommand),
    vscode.commands.registerCommand('aip.run', runCommand),
    vscode.commands.registerCommand('aip.publish', publishCommand),
    vscode.commands.registerCommand('aip.import', importCommand),
    { dispose: () => { for (const open of previews.values()) open.panel.dispose(); } },
  );

  paintStatus();
  refreshVersion().then(checkAll);
}

function deactivate() {}

module.exports = { activate, deactivate };
