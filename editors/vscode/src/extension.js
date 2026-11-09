'use strict';
/**
 * The extension's activation: on open, on every change (debounced) and on save, run the compiler
 * on the buffer's text and publish its diagnostics as squiggles; a status-bar item shows the
 * compiler's version, or "aip not found" with the install hint. The work is in compiler.js; this
 * file only talks to the `vscode` module.
 */

const vscode = require('vscode');
const compiler = require('./compiler');

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
    const result = await compiler.check({ ...settings(), file: document.fileName, source: document.getText() });
    if (document.isClosed || document.version !== version) return; // a later edit has its own check
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
  );

  paintStatus();
  refreshVersion().then(checkAll);
}

function deactivate() {}

module.exports = { activate, deactivate };
