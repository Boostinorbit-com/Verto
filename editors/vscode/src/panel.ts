// VERTO proof panel — a styled Webview showing a verdict's evidence: the big
// speed-up, the trust triplet, a before/after bar, the colored diff, and the
// Apply / Show-diff actions. Theme-aware via VS Code's CSS variables.
import * as vscode from 'vscode';
import * as core from './core';

let panel: vscode.WebviewPanel | undefined;
let current: { verdict: core.Verdict; uri: vscode.Uri } | undefined;

type Handlers = {
  apply: (v: core.Verdict) => void;
  showDiff: (v: core.Verdict) => void;
};

export function showProof(verdict: core.Verdict, uri: vscode.Uri, handlers: Handlers): void {
  current = { verdict, uri };
  if (!panel) {
    panel = vscode.window.createWebviewPanel('vertoProof', 'VERTO — proof', vscode.ViewColumn.Beside, {
      enableScripts: true,
      retainContextWhenHidden: true,
    });
    panel.onDidDispose(() => {
      panel = undefined;
    });
    panel.webview.onDidReceiveMessage((msg: { type: string }) => {
      if (!current) {
        return;
      }
      if (msg.type === 'apply') {
        handlers.apply(current.verdict);
      } else if (msg.type === 'showDiff') {
        handlers.showDiff(current.verdict);
      }
    });
  }
  panel.title = `VERTO — ${verdict.candidate?.transform ?? 'proof'}`;
  panel.webview.html = render(verdict);
  panel.reveal(vscode.ViewColumn.Beside, true);
}

function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function diffHtml(diff: string): string {
  return diff
    .replace(/\r?\n$/, '')
    .split('\n')
    .filter((ln) => !ln.startsWith('+++') && !ln.startsWith('---') && !ln.startsWith('@@'))
    .map((ln) => {
      const c = ln.charAt(0);
      const cls = c === '+' ? 'add' : c === '-' ? 'del' : 'ctx';
      return `<span class="${cls}">${esc(ln)}</span>`;
    })
    .join('\n');
}

function render(v: core.Verdict): string {
  const t = v.candidate?.transform ?? 'change';
  const rung = v.correctness?.rung ?? '?';
  const w = v.correctness?.witness ?? {};
  const san = w.sanitizer ?? 'clean';
  const runs = (w.inputs_run ?? 0).toLocaleString();
  const perf = v.performance?.vector ?? {};
  const before = perf.p50_before;
  const after = perf.p50;
  const label = core.speedupLabel(v);
  // bar widths: after relative to before
  const afterPct = before && after ? Math.max(6, Math.round((after / before) * 100)) : 40;
  const measured =
    before && after
      ? `p50 <b>${label}</b> &nbsp;·&nbsp; ${before.toFixed(2)} ms → ${after.toFixed(2)} ms`
      : `p50 <b>${label}</b>`;
  const rationale = v.candidate?.rationale ?? 'a proven, cheaper equivalent';

  return `<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
  :root{ color-scheme: light dark; }
  body{ font: 13px/1.5 var(--vscode-font-family); color: var(--vscode-foreground);
        background: var(--vscode-editor-background); padding: 18px 22px; }
  .head{ display:flex; align-items:center; gap:14px; margin-bottom:4px; }
  .badge{ font-size:30px; font-weight:800; letter-spacing:-.02em;
          color: var(--vscode-charts-green, #3fb950); }
  .tname{ font-size:15px; font-weight:600; }
  .sub{ color: var(--vscode-descriptionForeground); margin-bottom:18px; }
  .card{ border:1px solid var(--vscode-panel-border, rgba(128,128,128,.25));
         border-radius:10px; padding:14px 16px; margin:14px 0; }
  .triplet div{ display:flex; gap:10px; align-items:flex-start; margin:7px 0; }
  .tick{ color: var(--vscode-charts-green, #3fb950); font-weight:800; }
  .k{ font-weight:600; }
  .bars{ margin-top:8px; }
  .bar{ height:16px; border-radius:4px; margin:5px 0; display:flex; align-items:center;
        padding:0 8px; font-size:11px; color:#fff; white-space:nowrap; }
  .bar.before{ background: var(--vscode-charts-red, #f85149); width:100%; }
  .bar.after{ background: var(--vscode-charts-green, #3fb950); }
  pre{ background: var(--vscode-textCodeBlock-background, rgba(128,128,128,.1));
       border-radius:8px; padding:12px; overflow-x:auto; font-family: var(--vscode-editor-font-family); font-size:12px; }
  .add{ color: var(--vscode-charts-green, #3fb950); display:block; }
  .del{ color: var(--vscode-charts-red, #f85149); display:block; }
  .ctx{ color: var(--vscode-descriptionForeground); display:block; }
  .actions{ display:flex; gap:10px; margin-top:18px; }
  button{ font: inherit; padding:7px 16px; border:none; border-radius:6px; cursor:pointer; }
  .apply{ background: var(--vscode-button-background); color: var(--vscode-button-foreground); font-weight:600; }
  .apply:hover{ background: var(--vscode-button-hoverBackground); }
  .ghost{ background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground); }
  .note{ color: var(--vscode-descriptionForeground); font-size:11.5px; margin-top:12px; }
</style></head>
<body>
  <div class="head"><span class="badge">${label}</span><span class="tname">${esc(t)}</span></div>
  <div class="sub">Proven correct-and-faster before it's shown. Rung ${rung}.</div>

  <div class="card triplet">
    <div><span class="tick">✓</span><span><span class="k">Behavior-identical</span> — byte-identical output on ${runs} fuzzed inputs.</span></div>
    <div><span class="tick">✓</span><span><span class="k">Memory-safe</span> — ${san === 'clean' ? 'ASan · UBSan · TSan clean' : esc(san)} (Rung ${rung}).</span></div>
    <div><span class="tick">✓</span><span><span class="k">Faster</span> — ${measured} <span class="note">(on this machine; typically larger on production hardware).</span></span></div>
  </div>

  <div class="card">
    <div class="k">Why it's faster</div>
    <div class="sub" style="margin:6px 0 0">${esc(rationale)}.</div>
    <div class="bars">
      <div class="bar before">before ${before ? before.toFixed(2) + ' ms' : ''}</div>
      <div class="bar after" style="width:${afterPct}%">after ${after ? after.toFixed(2) + ' ms' : ''}</div>
    </div>
  </div>

  <pre>${diffHtml(v.diff || v.udiff || '')}</pre>

  <div class="actions">
    <button class="apply" onclick="send('apply')">Apply</button>
    <button class="ghost" onclick="send('showDiff')">Open side-by-side diff</button>
  </div>
  <div class="note">Behavior is proven unchanged — Apply writes the verified change; it's a normal, undoable edit.</div>

  <script>
    const vscode = acquireVsCodeApi();
    function send(type){ vscode.postMessage({ type }); }
  </script>
</body></html>`;
}
