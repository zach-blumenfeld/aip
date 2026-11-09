# AIP language: editor support

A VS Code extension for `.aip` procedure files: a TextMate grammar for the colours (also for
` ```aip ` fences in Markdown), and the compiler's diagnostics as squiggles. On open, on every
change and on save it runs `aip compile --check --json --stdin` on the file's folder with the
buffer's text, so an unsaved edit is checked against the folder's scripts and assets on disk,
and publishes every error, warning and info at the compiler's own line and column. A status-bar
item shows the compiler's version (`aip 0.9.0`), or "aip not found" with the install hint.

## Build

```
cd editors/vscode
npm install
npm run build          # esbuild bundles src/extension.js into dist/extension.js
npm test               # the tokenizer harness and the diagnostics tests, with node's test runner
```

The tests run the real compiler: `aip` on PATH, or the words in `AIP_COMMAND` (from a checkout,
`uv run aip`, the default). `npm run watch` rebuilds on every change.

## VS Code, Cursor, Windsurf

Build, then symlink this folder into the editor's extensions directory and reload the window:

```
ln -s "$(pwd)" ~/.vscode/extensions/aip-lang      # Cursor: ~/.cursor/extensions
```

Settings:

| Setting | Default | What it is |
|---|---|---|
| `aip.command` | `aip` | the command the extension runs: a name on PATH, a path, or several words such as `uv run aip` |
| `aip.debounceMs` | `300` | how long after the last edit the procedure is checked |

Commands: **AIP: Check the procedure** (check the active file now), **AIP: Show the compiler's
version** (the version line, or the install hint when `aip` is not found; also what clicking the
status-bar item does). The compiler's stderr, when it fails to answer, goes to the **AIP** output
channel.

## PyCharm and other JetBrains IDEs

Settings → Editor → TextMate Bundles → `+` → this folder gives the colors but not folding or
diagnostics: JetBrains IDEs do not fold TextMate-defined languages, and the diagnostics are the
VS Code extension's. A JetBrains custom file type was tried and dropped (2026-11-06); folding
there needs a native plugin.

## Sublime Text

Copy `syntaxes/aip.tmLanguage.json` into `Packages/User/`; Sublime converts it on load.

## Colors

The extension ships its own colors for its scopes (`contributes.configurationDefaults` in
`package.json`), so every theme shows the same scheme: step verbs bold and in the highest-contrast
color on the page, step names plain, every clause (`Read`, `Produce`, `Next_Step`, loop words,
`With`) in one blue, types teal, keys yellow, named strings green, labels and paths red, `{field}`
placeholders italic. A light-theme variant applies to themes whose name contains "Light". To
change a color, override the scope in your own `settings.json` under
`editor.tokenColorCustomizations.textMateRules`; user settings win over the extension's defaults.

## What it colors

Step verbs (`Decide`, `Route`, `Execute`, `Task_Agent`, `Start`, `End`, `Procedure`, `For`,
`Loop`) and the step name after them; clauses (`Read`, `Produce`, `Next_Step`, `Answer_Questions`,
`Agent_Fallback`, `Run_Script`, `Use`, `Prompt`, `Confidence_Below`, loop words); `->` and branch
labels; types; `key: type` declarations; `name = "..."` named strings; `decision.question` field
access; `{field}` placeholders inside strings; comments; numbers and `true`/`false`. Keywords match
in any case, as the compiler accepts them. `test/grammar.test.js` runs the grammar through
vscode-textmate over the example programs and asserts these scopes.

## Layout

| Path | What |
|---|---|
| `src/compiler.js` | runs the compiler, parses its report into ranges, reads its version; no `vscode` import, so node tests it |
| `src/extension.js` | the activation: documents, debounce, the diagnostic collection, the status bar, the commands |
| `esbuild.mjs` | the build; `dist/extension.js` is what `package.json`'s `main` names (not committed) |
| `syntaxes/` | the grammar and the Markdown injection |
| `test/` | `compiler.test.js` (against `test/fixtures/one-error`, a procedure with one error), `grammar.test.js` (the tokenizer harness) |
