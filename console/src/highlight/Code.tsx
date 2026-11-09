// Source text with line numbers; `procedure.aip` in the colours of the grammar the VS Code extension
// ships. The grammar and its colours are read from the extension itself (editors/vscode in this
// repository), bundled at build time: there is no copy of either here.

import { useMemo, type CSSProperties } from "react";
import grammarJson from "../../../editors/vscode/syntaxes/aip.tmLanguage.json";
import extensionJson from "../../../editors/vscode/package.json";
import { styleOf, tokenize, type RawGrammar, type ThemeRule } from "./textmate.ts";

const GRAMMAR = grammarJson as unknown as RawGrammar;

interface Customizations { textMateRules?: ThemeRule[]; "[*Light*]"?: { textMateRules?: ThemeRule[] } }

const CUSTOM = ((extensionJson as unknown as { contributes?: { configurationDefaults?: Record<string, unknown> } })
  .contributes?.configurationDefaults?.["editor.tokenColorCustomizations"] ?? {}) as Customizations;

// What an editor's theme colours and the extension therefore does not: comments, strings, numbers.
const BASE_DARK: ThemeRule[] = [
  { scope: "comment", settings: { foreground: "#7F8C8D", fontStyle: "italic" } },
  { scope: "string", settings: { foreground: "#CE9178" } },
  { scope: ["constant.numeric", "constant.language"], settings: { foreground: "#B5CEA8" } },
];
const BASE_LIGHT: ThemeRule[] = [
  { scope: "comment", settings: { foreground: "#6A737D", fontStyle: "italic" } },
  { scope: "string", settings: { foreground: "#A31515" } },
  { scope: ["constant.numeric", "constant.language"], settings: { foreground: "#098658" } },
];

/** The colour rules for the page's scheme: the extension's dark set, or its `[*Light*]` one. */
function themeRules(): ThemeRule[] {
  const dark = typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  return dark ? [...BASE_DARK, ...(CUSTOM.textMateRules ?? [])] : [...BASE_LIGHT, ...(CUSTOM["[*Light*]"]?.textMateRules ?? [])];
}

export const isProcedureSource = (path: string) => path.endsWith(".aip");

/** Monospace text with line numbers (CSS counters, starting at `firstLine`), highlighted when `aip`. */
export function Code({ text, aip = false, firstLine = 1 }: { text: string; aip?: boolean; firstLine?: number }) {
  const lines = useMemo(() => {
    const raw = text.endsWith("\n") ? text.slice(0, -1) : text;
    if (!aip) return raw.split("\n").map((line) => [{ text: line, style: {} as CSSProperties, scope: "" }]);
    const rules = themeRules();
    return tokenize(GRAMMAR, raw).map((tokens) => tokens.map((token) => {
      const s = styleOf(rules, token.scopes);
      const style: CSSProperties = {};
      if (s.color) style.color = s.color;
      if (s.bold) style.fontWeight = 600;
      if (s.italic) style.fontStyle = "italic";
      return { text: token.text, style, scope: token.scopes.length > 1 ? token.scopes[token.scopes.length - 1] : "" };
    }));
  }, [text, aip]);
  return (
    <ol className="code" data-testid="file-text" data-language={aip ? "aip" : undefined} style={{ counterReset: `line ${firstLine - 1}` }}>
      {lines.map((tokens, i) => (
        <li key={i}>
          {tokens.length === 0 || (tokens.length === 1 && tokens[0].text === "") ? "​"
            : tokens.map((t, j) => (t.scope ? <span key={j} style={t.style} data-scope={t.scope}>{t.text}</span> : t.text))}
        </li>
      ))}
    </ol>
  );
}
