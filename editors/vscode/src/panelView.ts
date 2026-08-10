// BOOSTOPT hybrid panel — the docked WebviewViewProvider (the locked UX direction).
// A conversational surface with full console power: natural-language requests OR
// `/`-prefixed raw commands, BOOSTOPT replies with the AI-propose → gate-filter pipeline
// and a verified result card, Apply / Show-diff inline. Drives the `boostopt` CLI; all
// verification is the engine, this is one more renderer of the same Verdict.
import * as cp from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import * as core from './core';

// A virtual-doc store for the native side-by-side diff (shared scheme with extension.ts is fine).
const afterDocs = new Map<string, string>();
let diffSeq = 1000;

// The panel is an editor-column webview, so while you type in it there is no
// "active text editor". Track the last C++ editor you touched, and target that.
let lastCppUri: vscode.Uri | undefined;
function rememberCpp(ed?: vscode.TextEditor): void {
  if (ed && ed.document.languageId === 'cpp') {
    lastCppUri = ed.document.uri;
  }
}
function resolveCppUri(): vscode.Uri | undefined {
  const active = vscode.window.activeTextEditor;
  if (active && active.document.languageId === 'cpp') {
    return active.document.uri;
  }
  if (lastCppUri) {
    return lastCppUri;
  }
  return vscode.window.visibleTextEditors.find((e) => e.document.languageId === 'cpp')?.document.uri;
}

export function registerAfterProvider(context: vscode.ExtensionContext): void {
  rememberCpp(vscode.window.activeTextEditor);
  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor(rememberCpp),
    vscode.workspace.registerTextDocumentContentProvider('boostopt-pdiff', {
      provideTextDocumentContent: (uri) => afterDocs.get(uri.toString()) ?? '',
    }),
  );
}

export class BoostoptPanel {
  private static current?: BoostoptPanel;
  private findings: core.Verdict[] = [];
  private targetUri?: vscode.Uri;

  /** Open (or reveal) the panel in the editor column to the RIGHT of the code. */
  static createOrShow(extensionUri: vscode.Uri): void {
    const column = vscode.ViewColumn.Beside;
    if (BoostoptPanel.current) {
      BoostoptPanel.current.panel.reveal(column, true);
      return;
    }
    const panel = vscode.window.createWebviewPanel(
      'boostopt.panel',
      'BOOSTOPT — Pair-optimizer',
      { viewColumn: column, preserveFocus: true },
      { enableScripts: true, retainContextWhenHidden: true, localResourceRoots: [extensionUri] },
    );
    panel.iconPath = vscode.Uri.joinPath(extensionUri, 'media', 'boostopt.svg');
    BoostoptPanel.current = new BoostoptPanel(panel);
  }

  private constructor(private readonly panel: vscode.WebviewPanel) {
    panel.webview.html = HTML;
    panel.onDidDispose(() => {
      BoostoptPanel.current = undefined;
    });
    panel.webview.onDidReceiveMessage(async (msg: { type: string; text?: string; index?: number }) => {
      if (msg.type === 'run' && msg.text) {
        await this.run(msg.text);
      } else if (msg.type === 'apply' && typeof msg.index === 'number') {
        await this.apply(msg.index);
      } else if (msg.type === 'showDiff' && typeof msg.index === 'number') {
        await this.showDiff(msg.index);
      } else if (msg.type === 'ready') {
        this.post({ type: 'profile', name: this.defaultProfile() });
      }
    });
  }

  private defaultProfile(): string {
    const folder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (folder) {
      try {
        const cfg = core.parseProfiles(fs.readFileSync(path.join(folder, '.boostopt.json'), 'utf8'));
        const keys = Object.keys(cfg.profiles);
        if (keys.length > 0) {
          return cfg.default && cfg.profiles[cfg.default] ? cfg.default : keys[0];
        }
      } catch {
        /* no .boostopt.json */
      }
    }
    return 'default';
  }

  private post(m: unknown): void {
    this.panel.webview.postMessage(m);
  }

  private profileArgs(uri: vscode.Uri): string[] {
    const cfg = vscode.workspace.getConfiguration('boostopt');
    const folder = vscode.workspace.getWorkspaceFolder(uri)?.uri.fsPath;
    let profiles: core.ProfileConfig | undefined;
    if (folder) {
      try {
        profiles = core.parseProfiles(fs.readFileSync(path.join(folder, '.boostopt.json'), 'utf8'));
      } catch {
        profiles = undefined;
      }
    }
    return core.profileArgs(profiles, undefined, cfg.get<string[]>('args', []));
  }

  private async run(text: string): Promise<void> {
    const uri = resolveCppUri();
    if (!uri) {
      this.post({ type: 'user', text });
      this.post({ type: 'error', text: 'Open a C++ file in a tab first — then ask me here and I\'ll target it.' });
      return;
    }
    this.targetUri = uri;
    this.post({ type: 'user', text });
    this.post({ type: 'thinking' });

    const cfg = vscode.workspace.getConfiguration('boostopt');
    const command = cfg.get<string>('command', 'boostopt');
    const raw = text.trim().startsWith('/');
    const extra = raw
      ? text.trim().slice(1).trim().split(/\s+/).filter(Boolean) // /-command: raw flags
      : this.profileArgs(this.targetUri); // natural language → active profile
    const args = ['optimize', this.targetUri.fsPath, '--json', '--no-daemon', ...extra];

    try {
      const out = await this.spawn(command, args, this.targetUri);
      const all = core.parseReport(out);
      this.findings = core.acceptedFindings(all);
      const rejected = core.nonAcceptedShown(all);

      const candidates = [
        ...this.findings.map((v) => ({ ok: true, name: transform(v), verdict: `verified ${core.speedupLabel(v)}` })),
        ...rejected.map((v) => ({ ok: false, name: transform(v), verdict: rejectReason(v) })),
      ];
      const result = this.findings[0] ? this.resultPayload(this.findings[0], 0) : null;
      const intro = result
        ? `Explored ${candidates.length} approach${candidates.length > 1 ? 'es' : ''} and proved each — here's the run:`
        : 'I ran the gate, but nothing cleared the correct-and-faster bar this time. Here’s what I tried:';
      this.post({ type: 'reply', intro, candidates, result });
    } catch (e) {
      this.post({ type: 'error', text: e instanceof Error ? e.message : String(e) });
    }
  }

  private resultPayload(v: core.Verdict, index: number) {
    return {
      index,
      speedup: core.speedupLabel(v),
      transform: transform(v),
      rung: v.correctness?.rung ?? '?',
      explanation: v.candidate?.rationale ?? 'a proven, cheaper equivalent',
      trust: `byte-identical on ${(v.correctness?.witness?.inputs_run ?? 0).toLocaleString()} fuzzed inputs · sanitizers clean · Rung ${v.correctness?.rung ?? '?'}`,
      diff: v.diff || v.udiff || '',
    };
  }

  private spawn(command: string, args: string[], uri: vscode.Uri): Promise<string> {
    return new Promise((resolve, reject) => {
      const parts = command.trim().split(/\s+/);
      const cwd = vscode.workspace.getWorkspaceFolder(uri)?.uri.fsPath;
      const proc = cp.spawn(parts[0], [...parts.slice(1), ...args], { cwd });
      let out = '';
      let err = '';
      proc.stdout.on('data', (d) => (out += d.toString()));
      proc.stderr.on('data', (d) => (err += d.toString()));
      proc.on('error', reject);
      proc.on('close', () => (out.trim() ? resolve(out) : reject(new Error(err.trim() || 'no output'))));
    });
  }

  private async doc(): Promise<vscode.TextDocument | undefined> {
    if (!this.targetUri) {
      return undefined;
    }
    const open = vscode.workspace.textDocuments.find((d) => d.uri.toString() === this.targetUri!.toString());
    return open ?? (await vscode.workspace.openTextDocument(this.targetUri));
  }

  private async apply(index: number): Promise<void> {
    const v = this.findings[index];
    const doc = await this.doc();
    if (!v || !doc) {
      return;
    }
    const hunks = core.parseHunks(v.udiff || v.diff || '').sort((a, b) => b.oldStart - a.oldStart);
    const edit = new vscode.WorkspaceEdit();
    for (const h of hunks) {
      const start = h.oldStart - 1;
      const end = Math.min(start + h.oldCount, doc.lineCount);
      edit.replace(doc.uri, new vscode.Range(start, 0, end, 0), h.newLines.join('\n') + '\n');
    }
    if (await vscode.workspace.applyEdit(edit)) {
      this.post({ type: 'applied', index, text: `Applied ${core.speedupLabel(v)} — ${transform(v)}. It's a normal, undoable edit.` });
    }
  }

  private async showDiff(index: number): Promise<void> {
    const v = this.findings[index];
    const doc = await this.doc();
    if (!v || !doc) {
      return;
    }
    const after = core.applyUdiff(doc.getText(), v.udiff || v.diff || '');
    const afterUri = doc.uri.with({ scheme: 'boostopt-pdiff', query: `v${diffSeq++}` });
    afterDocs.set(afterUri.toString(), after);
    const title = `${doc.uri.path.split('/').pop()} ↔ BOOSTOPT (${core.speedupLabel(v)})`;
    await vscode.commands.executeCommand('vscode.diff', doc.uri, afterUri, title, { preview: true });
  }
}

function transform(v: core.Verdict): string {
  return v.candidate?.transform ?? 'change';
}
function rejectReason(v: core.Verdict): string {
  const r = v.reason || '';
  if (r.startsWith('skipped')) return 'skipped';
  if (r === 'slower' || r === 'not_faster') return 'slower';
  if (r.indexOf('san') >= 0 || r.indexOf('race') >= 0) return 'sanitizer';
  return r.replace(/_/g, ' ');
}

// The webview UI — the BOOSTOPT console panel (matches Figma node 7-2): a command line,
// the AI-propose -> gate-filter pipeline, a verified result card with a colored diff,
// and a terminal-style input bar. Same run/apply/showDiff protocol as before.
const HTML = /* html */ `<!DOCTYPE html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline';">
<style>
  :root{ color-scheme: light dark; }
  *{ box-sizing:border-box; }
  body{ margin:0; font:12.5px/1.55 var(--vscode-font-family); color:var(--vscode-foreground);
        background:var(--vscode-sideBar-background,var(--vscode-editor-background)); display:flex; flex-direction:column; height:100vh; overflow-x:hidden; }
  .head{ display:flex; align-items:center; gap:10px; width:100%; padding:5px 12px;
         background:linear-gradient(90deg, rgba(120,90,220,.20), transparent 60%); border-bottom:1px solid var(--vscode-panel-border,rgba(128,128,128,.22)); }
  .brand{ flex:0 0 auto; font-size:13.5px; font-weight:800; letter-spacing:.05em; display:flex; align-items:center; gap:7px; color:var(--vscode-foreground); }
  .zap{ color:#f5b52a; font-size:14px; }
  .hspacer{ flex:1 1 auto; }
  .pchip{ flex:0 0 auto; font-size:11px; font-weight:700; color:#6ea8fe; background:rgba(255,255,255,.09); padding:3px 9px; border-radius:7px; white-space:nowrap; cursor:pointer; }
  .out{ flex:1; overflow-y:auto; padding:12px 14px; font-family:var(--vscode-editor-font-family,monospace); }
  .cmd{ margin:2px 0 6px; }
  .p{ color:#6a9cf5; font-weight:700; }
  .c{ color:var(--vscode-foreground); }
  .propose{ color:#b088f9; font-weight:600; font-family:var(--vscode-font-family); margin:9px 0 4px; }
  .cand{ display:flex; gap:8px; align-items:center; margin:2px 0; }
  .cand .ic{ font-weight:700; } .cand.ok .ic{ color:#3fb950; } .cand.no .ic{ color:#6b6f76; }
  .cand .nm{ flex:1; } .cand.ok .nm{ color:var(--vscode-foreground); } .cand.no .nm{ color:#6b6f76; }
  .cand.ok .vd{ color:#3fb950; font-weight:600; } .cand.no .vd{ color:#c17b78; }
  .summary{ margin:7px 0 2px; color:var(--vscode-foreground); font-weight:600; font-family:var(--vscode-font-family); }
  .card{ border:1px solid rgba(63,185,80,.5); border-radius:9px; padding:12px; margin:10px 0; background:rgba(255,255,255,.02); font-family:var(--vscode-font-family); }
  .card .t{ font-weight:700; } .card .t .g{ color:#3fb950; } .card .t .nm{ color:var(--vscode-descriptionForeground); font-weight:400; }
  .card .ex{ margin:6px 0; } .card .ex b{ color:#b088f9; }
  .card .tr{ color:var(--vscode-descriptionForeground); font-size:11.5px; }
  .diff{ background:rgba(0,0,0,.35); border-radius:7px; padding:10px 12px; margin:9px 0; overflow-x:auto; font-family:var(--vscode-editor-font-family,monospace); font-size:11.5px; }
  .diff .a{ color:#52c168; display:block; white-space:pre; } .diff .d{ color:#f2726b; display:block; white-space:pre; } .diff .x{ color:var(--vscode-descriptionForeground); display:block; white-space:pre; }
  .btns{ display:flex; gap:8px; margin-top:7px; }
  button{ font:inherit; border:none; border-radius:6px; padding:5px 14px; cursor:pointer; font-weight:600; font-family:var(--vscode-font-family); }
  .apply{ background:var(--vscode-button-background); color:var(--vscode-button-foreground); }
  .ghost{ background:var(--vscode-button-secondaryBackground,#3a3d41); color:var(--vscode-button-secondaryForeground,#fff); }
  .dim{ color:var(--vscode-descriptionForeground); font-style:italic; margin:4px 0; }
  .err{ color:var(--vscode-errorForeground,#f88); margin:4px 0; }
  .inputbar{ display:flex; align-items:center; gap:8px; padding:9px 12px; border-top:1px solid var(--vscode-panel-border,rgba(128,128,128,.22)); font-family:var(--vscode-editor-font-family,monospace); }
  .inputbar .p{ flex:0 0 auto; }
  #inp{ flex:1; background:transparent; border:none; outline:none; color:var(--vscode-foreground); font:inherit; }
  .run{ display:flex; align-items:center; gap:5px; background:var(--vscode-button-background); color:var(--vscode-button-foreground); border-radius:6px; padding:6px 14px; font-family:var(--vscode-font-family); }
</style></head>
<body>
  <div class="head">
    <div class="brand"><span class="zap">⚡</span>BOOSTOPT</div>
    <div class="hspacer"></div>
    <div class="pchip" id="prof">profile: default ▾</div>
  </div>
  <div class="out" id="out"><div class="dim">Ask below to optimize the active C++ file — or type /optimize with raw flags.</div></div>
  <div class="inputbar">
    <input id="inp" placeholder="Ask to optimize the active C++ file…  or /optimize --flags">
  </div>
<script>
  const vscode = acquireVsCodeApi();
  const out = document.getElementById('out');
  const inp = document.getElementById('inp');
  const esc = s => (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  let thinkEl = null;
  function add(html){ const d=document.createElement('div'); d.innerHTML=html; out.appendChild(d); out.scrollTop=out.scrollHeight; return d; }
  function cmdLine(t){ add('<div class="cmd"><span class="p">boostopt ▸</span> <span class="c">'+esc(t)+'</span></div>'); }
  function think(){ thinkEl = add('<div class="dim">proposing &amp; verifying…</div>'); }
  function clearThink(){ if(thinkEl){ thinkEl.remove(); thinkEl=null; } }

  function diffHtml(diff){
    return (diff||'').replace(/\\r?\\n$/,'').split('\\n')
      .filter(l => !l.startsWith('+++') && !l.startsWith('---') && !l.startsWith('@@'))
      .map(l => { const c=l.charAt(0); const cls=c==='+'?'a':c==='-'?'d':'x'; return '<span class="'+cls+'">'+esc(l)+'</span>'; }).join('');
  }

  function reply(m){
    clearThink();
    if(m.candidates && m.candidates.length){
      add('<div class="propose">AI proposed '+m.candidates.length+' optimization'+(m.candidates.length>1?'s':'')+' — the gate verified each</div>');
      for(const c of m.candidates){
        add('<div class="cand '+(c.ok?'ok':'no')+'"><span class="ic">'+(c.ok?'✓':'✗')+'</span><span class="nm">'+esc(c.name)+'</span><span class="vd">'+esc(c.verdict)+'</span></div>');
      }
    }
    if(m.result){
      const r=m.result;
      const nAcc=(m.candidates||[]).filter(c=>c.ok).length, nRej=(m.candidates||[]).length-nAcc;
      add('<div class="summary">→ '+nAcc+' verified · '+nRej+' rejected. You only ever see the proven one.</div>');
      add('<div class="card"><div class="t"><span class="g">✓</span> verified <span class="g">'+esc(r.speedup)+'</span> <span class="nm">· '+esc(r.transform)+'</span></div>'
        + '<div class="ex"><b>AI</b> · '+esc(r.explanation)+'.</div>'
        + '<div class="tr">'+esc(r.trust)+'</div>'
        + (r.diff ? '<div class="diff">'+diffHtml(r.diff)+'</div>' : '')
        + '<div class="btns"><button class="apply" data-apply="'+r.index+'">Apply</button><button class="ghost" data-diff="'+r.index+'">Diff</button></div></div>');
    } else {
      add('<div class="dim">Nothing cleared the correct-and-faster bar this run.</div>');
    }
  }

  function send(){ const t=inp.value.trim(); if(!t) return; inp.value=''; vscode.postMessage({type:'run', text:t}); }
  inp.addEventListener('keydown', e => { if(e.key==='Enter'){ e.preventDefault(); send(); } });
  out.addEventListener('click', e => {
    const t=e.target;
    if(t.dataset && t.dataset.apply!==undefined) vscode.postMessage({type:'apply', index:+t.dataset.apply});
    else if(t.dataset && t.dataset.diff!==undefined) vscode.postMessage({type:'showDiff', index:+t.dataset.diff});
  });

  window.addEventListener('message', ev => {
    const m=ev.data;
    if(m.type==='user') cmdLine(m.text);
    else if(m.type==='thinking') think();
    else if(m.type==='reply') reply(m);
    else if(m.type==='applied'){ clearThink(); add('<div class="summary"><span style="color:#3fb950">✓</span> '+esc(m.text)+'</div>'); }
    else if(m.type==='error'){ clearThink(); add('<div class="err">'+esc(m.text)+'</div>'); }
    else if(m.type==='profile'){ const p=document.getElementById('prof'); if(p) p.textContent='profile: '+m.name+' ▾'; }
  });
  vscode.postMessage({type:'ready'});
</script>
</body></html>`;
