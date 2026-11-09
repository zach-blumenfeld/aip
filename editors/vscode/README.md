# AIP language: editor support

A TextMate grammar for `.aip` files, packaged as a VS Code extension. It also highlights
` ```aip ` fences in Markdown. No publishing, no build step.

## VS Code, Cursor, Windsurf

Symlink this folder into the editor's extensions directory and reload the window:

```
ln -s "$(pwd)" ~/.vscode/extensions/aip-lang      # Cursor: ~/.cursor/extensions
```

## PyCharm and other JetBrains IDEs

Settings → Editor → TextMate Bundles → `+` → this folder gives the colors but not folding: JetBrains
IDEs do not fold TextMate-defined languages. A JetBrains custom file type was tried and dropped
(2026-11-06); folding there needs a native plugin.

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
in any case, as the compiler accepts them.
