// BOOSTOPT VS Code extension — pure logic (NO `vscode` import, so it is unit-testable
// off the editor). Turns `boostopt … --json` output into what the editor renders, and
// applies a verified diff. The vscode glue in extension.ts calls into here.

/** The subset of BOOSTOPT's `Verdict` JSON the extension uses. */
export interface Verdict {
  accepted: boolean;
  reason: string;
  candidate?: { transform?: string; rationale?: string } | null;
  correctness?: { rung?: number; witness?: { sanitizer?: string; inputs_run?: number } } | null;
  performance?: { vector?: Record<string, number>; pareto_pass?: boolean } | null;
  diff?: string;
  udiff?: string;
  applied?: boolean;
  tests_confirmed?: boolean;
  via?: string;
}

/**
 * `boostopt <file> --json` emits a `Verdict[]`; the codebase form emits
 * `[{file, verdicts, …}]`. Accept either and return a flat `Verdict[]`.
 */
export function parseReport(stdout: string): Verdict[] {
  const data = JSON.parse(stdout);
  if (Array.isArray(data) && data.length > 0 && data[0] && 'verdicts' in data[0]) {
    return (data as Array<{ verdicts?: Verdict[] }>).flatMap((f) => f.verdicts ?? []);
  }
  return (data ?? []) as Verdict[];
}

export function acceptedFindings(vs: Verdict[]): Verdict[] {
  return vs.filter((v) => v.accepted);
}

// Reasons that mean "the proposer produced no usable change" — loop bookkeeping,
// not a real reject of a candidate. Hidden from the human, per the CLI's own rule.
const INTERNAL_REASONS = new Set(['mutation_failed', 'precondition_failed']);

/** Non-accepted verdicts worth reporting (skips + real rejects), minus loop noise. */
export function nonAcceptedShown(vs: Verdict[]): Verdict[] {
  return vs.filter((v) => !v.accepted && !INTERNAL_REASONS.has(v.reason));
}

export function isSkip(v: Verdict): boolean {
  return (v.reason ?? '').startsWith('skipped');
}

/** A one-line "why not accepted" summary for the honest-silence report. */
export function outcomeLine(v: Verdict): string {
  const t = v.candidate?.transform ?? '?';
  const verb = isSkip(v) ? 'skipped' : 'rejected';
  return `${verb}: ${t} — ${v.reason}`;
}

// ── Project run-profiles (.boostopt.json) ─────────────────────────────────────────
// A committed, team-shared file where developers define named flag-sets, e.g.
//   { "default": "quick",
//     "profiles": {
//       "quick":    { "description": "fast, deterministic", "args": ["--model","rules"] },
//       "thorough": { "args": ["--min-rung","3","--metamorphic","--fuzz","5000"] } } }

export interface Profile {
  description?: string;
  args: string[];
}
export interface ProfileConfig {
  default?: string;
  profiles: Record<string, Profile>;
}

/** Parse a .boostopt.json into a validated ProfileConfig (tolerant of missing bits). */
export function parseProfiles(text: string): ProfileConfig {
  const data = JSON.parse(text) as { default?: unknown; profiles?: Record<string, unknown> };
  const profiles: Record<string, Profile> = {};
  for (const [name, raw] of Object.entries(data.profiles ?? {})) {
    const p = (raw ?? {}) as { description?: unknown; args?: unknown };
    profiles[name] = {
      description: typeof p.description === 'string' ? p.description : undefined,
      args: Array.isArray(p.args) ? p.args.map(String) : [],
    };
  }
  return { default: typeof data.default === 'string' ? data.default : undefined, profiles };
}

/** The args for the chosen profile — falling back to default, then first, then `fallback`. */
export function profileArgs(
  cfg: ProfileConfig | undefined,
  name: string | undefined,
  fallback: string[],
): string[] {
  if (!cfg || Object.keys(cfg.profiles).length === 0) {
    return fallback;
  }
  const pick =
    (name && cfg.profiles[name] && name) ||
    (cfg.default && cfg.profiles[cfg.default] && cfg.default) ||
    Object.keys(cfg.profiles)[0];
  return pick ? cfg.profiles[pick].args : fallback;
}

export function deltaPct(v: Verdict): number | undefined {
  return v.performance?.vector?.p50_delta_pct;
}

/** "−52%" (a reduction is a win) or "faster" when the number isn't available. */
export function speedupLabel(v: Verdict): string {
  const d = deltaPct(v);
  return d ? `−${Math.round(d)}%` : 'faster';
}

/** A unified-diff hunk: the OLD-side line range + the NEW-side replacement text. */
export interface Hunk {
  oldStart: number; // 1-based
  oldCount: number;
  newLines: string[];
}

export function parseHunks(udiff: string): Hunk[] {
  const hunks: Hunk[] = [];
  let cur: Hunk | null = null;
  for (const ln of (udiff || '').split('\n')) {
    const m = /^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@/.exec(ln);
    if (m) {
      if (cur) hunks.push(cur);
      cur = { oldStart: parseInt(m[1], 10), oldCount: m[2] ? parseInt(m[2], 10) : 1, newLines: [] };
    } else if (cur) {
      const c = ln.charAt(0);
      if (c === ' ' || c === '+') cur.newLines.push(ln.slice(1)); // '-' lines are dropped
    }
  }
  if (cur) hunks.push(cur);
  return hunks;
}

/** 1-based line a finding anchors to (its first hunk) — for CodeLens/hover placement. */
export function anchorLine(v: Verdict): number {
  const hs = parseHunks(v.udiff || v.diff || '');
  return hs.length > 0 ? hs[0].oldStart : 1;
}

/** True if `line1` (1-based) sits inside any of the finding's changed hunks. */
export function coversLine(v: Verdict, line1: number): boolean {
  return parseHunks(v.udiff || v.diff || '').some(
    (h) => line1 >= h.oldStart && line1 < h.oldStart + h.oldCount,
  );
}

/**
 * Apply a udiff to source text (pure — the editor path in extension.ts mirrors this
 * with a WorkspaceEdit). Each hunk's old-line span is replaced by its new content;
 * hunks are applied bottom-up so earlier line numbers stay valid.
 */
export function applyUdiff(source: string, udiff: string): string {
  const lines = source.split('\n');
  const hunks = parseHunks(udiff).sort((a, b) => b.oldStart - a.oldStart);
  for (const h of hunks) {
    lines.splice(h.oldStart - 1, h.oldCount, ...h.newLines);
  }
  return lines.join('\n');
}

/** The trust triplet as Markdown, for the hover. */
export function proofMarkdown(v: Verdict): string {
  const c = v.correctness ?? {};
  const w = c.witness ?? {};
  const perf = v.performance?.vector ?? {};
  const rung = c.rung ?? '?';
  const san = w.sanitizer ?? 'clean';
  const runs = w.inputs_run ?? 0;
  const transform = v.candidate?.transform ?? 'change';

  const out: string[] = [
    `**BOOSTOPT — ${transform}**`,
    '',
    `**Why it's safe** — byte-identical on ${runs.toLocaleString()} fuzzed inputs; ` +
      `${san === 'clean' ? 'sanitizers clean' : san} (Rung ${rung}).`,
  ];
  if (v.candidate?.rationale) {
    out.push(`**Why it's faster** — ${v.candidate.rationale}.`);
  }
  const p50 = perf.p50;
  const before = perf.p50_before;
  out.push(
    p50 && before
      ? `**Measured** — p50 ${speedupLabel(v)} (${before.toFixed(2)} ms → ${p50.toFixed(2)} ms, on this machine).`
      : `**Measured** — p50 ${speedupLabel(v)} (on this machine).`,
  );
  return out.join('\n');
}
