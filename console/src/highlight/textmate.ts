// A small TextMate tokenizer: enough of the format to run the grammar the VS Code extension ships
// (editors/vscode/syntaxes/aip.tmLanguage.json), so the console colours `procedure.aip` from the same
// rules an editor does and there is no second list of keywords. It handles what that grammar uses:
// `match`, `begin`/`end`, `captures`, `beginCaptures`, `endCaptures`, `patterns`, `include: "#name"`,
// and a leading `(?i)`. It does not handle `while`, `\G`, back-references into the end pattern, or
// captures nested in captures. No imports and no DOM: it runs under node as it is (test/highlight.test.ts).

export interface RawCapture { name?: string }
export type RawCaptures = Record<string, RawCapture>;

export interface RawRule {
  name?: string;
  comment?: string;
  match?: string;
  begin?: string;
  end?: string;
  captures?: RawCaptures;
  beginCaptures?: RawCaptures;
  endCaptures?: RawCaptures;
  patterns?: RawRule[];
  include?: string;
}

export interface RawGrammar {
  scopeName: string;
  patterns: RawRule[];
  repository?: Record<string, RawRule>;
}

/** A run of text and every scope it is under, outermost first. */
export interface Token { text: string; scopes: string[] }

interface Context {
  rules: RawRule[];
  end: string | null;
  endCaptures: RawCaptures | undefined;
  scopes: string[];
}

/** The tokenizer's state between lines: the open `begin`/`end` rules (a triple-quoted string spans lines). */
export type State = Context[];

/** A match with the `d` flag's `indices`: where each group matched (a group that did not has none). */
type Match = RegExpExecArray;

const compiled = new Map<string, RegExp>();

function regex(pattern: string): RegExp {
  let found = compiled.get(pattern);
  if (!found) {
    const insensitive = pattern.startsWith("(?i)");
    found = new RegExp(insensitive ? pattern.slice(4) : pattern, insensitive ? "dgi" : "dg");
    compiled.set(pattern, found);
  }
  return found;
}

/** The first match of `pattern` in `line` at or after `from`. `^` holds only at the start of the line. */
function search(pattern: string, line: string, from: number): Match | null {
  const re = regex(pattern);
  re.lastIndex = from;
  return re.exec(line) as Match | null;
}

/** `patterns` with includes and groups flattened into the rules that match or begin something. */
function rulesOf(grammar: RawGrammar, patterns: RawRule[] | undefined): RawRule[] {
  const out: RawRule[] = [];
  for (const p of patterns ?? []) {
    if (p.include !== undefined) {
      const target = p.include.startsWith("#") ? grammar.repository?.[p.include.slice(1)] : undefined;
      if (target) out.push(...rulesOf(grammar, [target]));
    } else if (p.match !== undefined || p.begin !== undefined) {
      out.push(p);
    } else if (p.patterns) {
      out.push(...rulesOf(grammar, p.patterns));
    }
  }
  return out;
}

export function initialState(grammar: RawGrammar): State {
  return [{ rules: rulesOf(grammar, grammar.patterns), end: null, endCaptures: undefined, scopes: [grammar.scopeName] }];
}

/** `line[start, end)` under `scopes`, the captured groups under their own names as well. */
function emit(out: Token[], line: string, m: Match, captures: RawCaptures | undefined, scopes: string[]): void {
  const start = m.index, end = m.index + m[0].length;
  const spans: { from: number; to: number; name: string }[] = [];
  for (const [key, capture] of Object.entries(captures ?? {})) {
    const range = m.indices?.[Number(key)];
    if (range && capture.name && range[1] > range[0]) spans.push({ from: range[0], to: range[1], name: capture.name });
  }
  spans.sort((a, b) => a.from - b.from);
  let pos = start;
  for (const span of spans) {
    if (span.from < pos || span.to > end) continue;
    if (span.from > pos) out.push({ text: line.slice(pos, span.from), scopes });
    out.push({ text: line.slice(span.from, span.to), scopes: [...scopes, span.name] });
    pos = span.to;
  }
  if (pos < end) out.push({ text: line.slice(pos, end), scopes });
}

/** One line's tokens. `state` is changed in place: pass the same one to the next line. */
export function tokenizeLine(grammar: RawGrammar, line: string, state: State): Token[] {
  const out: Token[] = [];
  let pos = 0;
  let stuck = 0;
  while (pos <= line.length) {
    const top = state[state.length - 1];
    let best: { kind: "end" | "match" | "begin"; rule: RawRule | null; m: Match } | null = null;
    if (top.end !== null) {
      const m = search(top.end, line, pos);
      if (m) best = { kind: "end", rule: null, m };
    }
    for (const rule of top.rules) {
      const m = search((rule.match ?? rule.begin) as string, line, pos);
      if (!m) continue;
      if (rule.match !== undefined && m[0].length === 0) continue;
      if (best === null || m.index < best.m.index) best = { kind: rule.match !== undefined ? "match" : "begin", rule, m };
    }
    if (best === null) break;
    const { kind, rule, m } = best;
    if (m.index > pos) out.push({ text: line.slice(pos, m.index), scopes: top.scopes });
    if (kind === "end") {
      emit(out, line, m, top.endCaptures, top.scopes);
      state.pop();
    } else {
      const r = rule as RawRule;
      const scopes = r.name ? [...top.scopes, r.name] : top.scopes;
      if (kind === "match") {
        emit(out, line, m, r.captures, scopes);
      } else {
        emit(out, line, m, r.beginCaptures ?? r.captures, scopes);
        state.push({ rules: rulesOf(grammar, r.patterns), end: r.end ?? null, endCaptures: r.endCaptures ?? r.captures, scopes });
      }
    }
    const next = m.index + m[0].length;
    if (next === pos) {
      // An empty match that changed only the stack (an `end` of `$`): let it settle, but never spin.
      stuck += 1;
      if (stuck > 4) {
        if (pos < line.length) out.push({ text: line[pos], scopes: state[state.length - 1].scopes });
        pos += 1;
        stuck = 0;
      }
    } else {
      stuck = 0;
      pos = next;
    }
  }
  if (pos < line.length) out.push({ text: line.slice(pos), scopes: state[state.length - 1].scopes });
  return out;
}

/** Every line of `text` as tokens; joined, a line's tokens are the line. */
export function tokenize(grammar: RawGrammar, text: string): Token[][] {
  const state = initialState(grammar);
  return text.split("\n").map((line) => tokenizeLine(grammar, line, state));
}

// ------------------------------------------------------------------ colours

/** One `textMateRules` entry of a VS Code theme or of an extension's `configurationDefaults`. */
export interface ThemeRule { scope: string | string[]; settings: { foreground?: string; fontStyle?: string } }

export interface Style { color?: string; bold?: boolean; italic?: boolean }

/** The style of a token: the rule naming the longest prefix of its innermost scope that any rule names
 *  (`keyword.other` colours `keyword.other.clause.aip`), looking outward scope by scope. */
export function styleOf(rules: ThemeRule[], scopes: string[]): Style {
  for (let i = scopes.length - 1; i >= 0; i--) {
    let best: ThemeRule | null = null;
    let length = -1;
    for (const rule of rules) {
      for (const selector of Array.isArray(rule.scope) ? rule.scope : [rule.scope]) {
        if ((scopes[i] === selector || scopes[i].startsWith(selector + ".")) && selector.length > length) {
          best = rule;
          length = selector.length;
        }
      }
    }
    if (best) {
      const style = best.settings.fontStyle ?? "";
      return { color: best.settings.foreground, bold: style.includes("bold"), italic: style.includes("italic") };
    }
  }
  return {};
}
