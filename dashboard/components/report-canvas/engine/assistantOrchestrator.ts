/* ═══════════════════════════════════════════════════════════════════
   Assistant orchestrator (S3) — natural-language intent → tool routing
   + proactive, document-aware suggestions.

   This is the "brain" that replaces the brittle keyword regex. It maps
   free-form officer language onto the EXISTING tool surface (inspect,
   regenerate, shorten, update, remove, outline, list, layout, fit,
   repack, balance) and falls through to the DeepAgent (deep_bi) for
   genuine analysis questions.

   Pure + framework-free so it is unit-testable and model-swappable: the
   scoring classifier here is a fast local stand-in that can later be
   replaced by an LLM `{tool,args}` call without changing the tool surface.
   ═══════════════════════════════════════════════════════════════════ */

export type IntentTool =
  | 'inspect' | 'regenerate' | 'shorten' | 'update' | 'remove'
  | 'outline' | 'list' | 'layout' | 'fit' | 'repack' | 'balance'
  | 'footnote' | 'deep_bi' | 'help';

export interface Intent {
  tool: IntentTool;
  /** Target component index, if the message named or implied one. */
  index?: number;
  /** Replacement text for update, captured from quotes. */
  text?: string;
  /** Confidence 0..1 (how sure the classifier is). */
  score: number;
}

/** Synonym groups — natural phrasing an officer actually uses. */
const PATTERNS: Array<{ tool: IntentTool; res: RegExp[]; score: number }> = [
  { tool: 'shorten',  score: 0.9, res: [/\b(short(er|en)?|trim|condense|tighten|cut down|too long|brief(er)?|crisp)\b/] },
  { tool: 'regenerate', score: 0.9, res: [/\b(regenerate|re-?generate|redo|re-?run|refresh|rebuild|try again|do (it )?again)\b/] },
  { tool: 'inspect',  score: 0.85, res: [/\b(inspect|explain|detail|why|how.*(computed|derived|calculated)|where.*(from|source)|provenance|data source)\b/] },
  { tool: 'remove',   score: 0.9, res: [/\b(remove|delete|drop|get rid of|take out)\b/] },
  { tool: 'update',   score: 0.8, res: [/\b(update|change|replace|set|rewrite|edit).*(text|to|with)\b/, /["“”'].+["“”']/] },
  { tool: 'outline',  score: 0.85, res: [/\b(outline|structure|table of contents|toc|sections?|hierarchy|headings?)\b/] },
  { tool: 'list',     score: 0.8, res: [/\b(list|all components?|queue|what.*(generated|pending|done)|status of|overview)\b/] },
  { tool: 'layout',   score: 0.85, res: [/\b(layout|page.*(full|space|fill)|how full|space (left|remaining)|fit on (the )?page)\b/] },
  { tool: 'fit',      score: 0.8, res: [/\b(fit|make.*fit|right-?size|fill the (gap|space)|squeeze)\b/] },
  { tool: 'repack',   score: 0.85, res: [/\b(repack|re-?flow|re-?pack|re-?paginate|tidy.*(pages|layout)|fix.*(gaps?|spacing))\b/] },
  { tool: 'balance',  score: 0.8, res: [/\b(balance|rebalance|even.*(out|spacing)|distribute|whitespace)\b/] },
  { tool: 'footnote', score: 0.85, res: [/\b(footnote|caveat|note|caution|flag|reliability|provisional|revised)\b/] },
];

/** Extract the first integer in the text (component index). */
function extractIndex(text: string): number | undefined {
  const m = text.match(/(?:^|\s|#|component\s*)(\d{1,3})\b/i);
  return m ? parseInt(m[1], 10) : undefined;
}

/** Extract quoted replacement text for update. */
function extractQuoted(text: string): string | undefined {
  const m = text.match(/["“”'](.+?)["“”']/);
  return m ? m[1] : undefined;
}

/**
 * Classify a free-form message into an intent over the existing tools.
 * Returns the best-scoring tool; `deep_bi` when it reads like an analysis
 * question; `help` only when truly ambiguous AND short.
 */
export function classifyIntent(message: string): Intent {
  const text = message.trim();
  const lower = text.toLowerCase();

  // Slash commands are explicit — honour them directly.
  if (/^\/(layout)/.test(lower)) return { tool: 'layout', score: 1 };
  if (/^\/(repack)/.test(lower)) return { tool: 'repack', score: 1 };
  if (/^\/(balance)/.test(lower)) return { tool: 'balance', score: 1 };
  if (/^\/(fit)/.test(lower)) return { tool: 'fit', score: 1 };

  let best: Intent = { tool: 'deep_bi', score: 0.3 };
  for (const p of PATTERNS) {
    if (p.res.some((re) => re.test(lower))) {
      if (p.score > best.score) best = { tool: p.tool, score: p.score };
    }
  }

  // Status/bundle questions ("what's pending", "what's done") are LOCAL tools,
  // not data analysis — check before the analysis-shape override.
  if (/\b(pending|generated|done|remaining|failed|still.*(to do|left)|progress|status)\b/.test(lower)
      && /\b(what|which|how many|show|list|any|are there)\b/.test(lower)) {
    return { tool: 'list', score: 0.95, index: extractIndex(text) };
  }

  // Analysis-question shape → DeepAgent, not a local tool.
  const analysisShape = /\b(what|which|how many|compare|trend|rank|top|highest|lowest|share|distribution|correlat|average|total of|growth|change in)\b/.test(lower);
  if (best.tool === 'deep_bi' && !analysisShape && text.split(/\s+/).length <= 3) {
    best = { tool: 'help', score: 0.4 };
  }
  // Only fall to deep_bi when there's no confident local-tool match.
  if (analysisShape && best.score < 0.8) {
    best = { tool: 'deep_bi', score: 0.7 };
  }

  best.index = extractIndex(text);
  if (best.tool === 'update') best.text = extractQuoted(text);
  return best;
}

/* ── Proactive suggestions (S3 ③) ─────────────────────────────────── */

export interface Suggestion {
  id: string;
  label: string;       // officer-language
  kind: 'generate' | 'quality' | 'layout' | 'review';
  /** The message to dispatch when the chip is clicked. */
  command: string;
}

export interface SuggestionInputs {
  pendingTopics: Array<{ topic: string; pending: number }>;
  failedCount: number;
  emptiestPage?: { page: number; fillPct: number };
  /** Tables that carry a caution (*) marker — candidates for a footnote. */
  unreliableTables: string[];
  totalPending: number;
}

/**
 * Build a small, ranked set of proactive suggestions from the live document
 * state. Kept deliberately short (max 4) so it advises without nagging.
 */
export function buildSuggestions(inp: SuggestionInputs): Suggestion[] {
  const out: Suggestion[] = [];

  if (inp.failedCount > 0) {
    out.push({
      id: 'retry-failed',
      label: `Retry ${inp.failedCount} failed component${inp.failedCount > 1 ? 's' : ''}`,
      kind: 'generate',
      command: 'retry failed',
    });
  }

  for (const t of inp.pendingTopics.slice(0, 2)) {
    out.push({
      id: `gen-${t.topic}`,
      label: `Generate “${t.topic}” (${t.pending} pending)`,
      kind: 'generate',
      command: `generate topic ${t.topic}`,
    });
  }

  for (const tbl of inp.unreliableTables.slice(0, 1)) {
    out.push({
      id: `footnote-${tbl}`,
      label: `Footnote ${tbl} — has an unreliable estimate`,
      kind: 'quality',
      command: `add footnote to ${tbl}`,
    });
  }

  if (inp.emptiestPage && inp.emptiestPage.fillPct < 55 && out.length < 4) {
    out.push({
      id: 'balance',
      label: `Page ${inp.emptiestPage.page} is ${inp.emptiestPage.fillPct}% full — tighten layout`,
      kind: 'layout',
      command: '/balance',
    });
  }

  return out.slice(0, 4);
}
