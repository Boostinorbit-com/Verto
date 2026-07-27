// VERTO VS Code extension — the editor glue. Implements the design note's §5 surfaces:
//   • an "optimize this file" CodeLens that resolves to "verified −X%" (two-state)
//   • the command + a right-click code action (the 💡 lightbulb)
//   • proof-on-hover, Apply, and Show diff
//   • honest silence: what was tried and why it didn't make the cut, in an output channel
// All verification is the `verto` CLI; this file only renders its `--json` Verdicts.
import * as cp from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import * as core from './core';
import * as panel from './panel';
import { VertoPanel, registerAfterProvider } from './panelView';

// Virtual "after" documents for the native side-by-side diff (verto-after: scheme).
const afterDocs = new Map<string, string>();
let diffSeq = 0;

// Selected run-profile (from .verto.json), and the status-bar item that shows it.
let activeProfile: string | undefined;
let statusItem: vscode.StatusBarItem;

/** Read the project's .verto.json (team-shared run profiles), or undefined. */
function loadProfiles(uri: vscode.Uri): core.ProfileConfig | undefined {
  const folder = vscode.workspace.getWorkspaceFolder(uri)?.uri.fsPath;
  if (!folder) {
    return undefined;
  }
  const file = path.join(folder, '.verto.json');
  try {
    return core.parseProfiles(fs.readFileSync(file, 'utf8'));
  } catch {
    return undefined; // absent or malformed → fall back to the verto.args setting
  }
}

function updateStatus(): void {
  const uri = vscode.window.activeTextEditor?.document.uri;
  const cfg = uri ? loadProfiles(uri) : undefined;
  if (cfg && Object.keys(cfg.profiles).length > 0) {
    const name = activeProfile && cfg.profiles[activeProfile] ? activeProfile : cfg.default ?? Object.keys(cfg.profiles)[0];
    statusItem.text = `$(zap) VERTO: ${name}`;
    statusItem.tooltip = 'VERTO run profile (from .verto.json) — click to switch';
    statusItem.show();
  } else {
    statusItem.hide();
  }
}

// State for the one document we last verified (MVP scope: current file).
let findings: core.Verdict[] = []; // accepted only — what gets a CodeLens
let allVerdicts: core.Verdict[] = []; // everything, for the honest-silence report
let resultUri: string | undefined; // the doc `findings` belong to
const ran = new Set<string>(); // docs we've run at least once (drives the two-state lens)
const lensChanged = new vscode.EventEmitter<void>();
let output: vscode.OutputChannel;

export function activate(context: vscode.ExtensionContext): void {
  output = vscode.window.createOutputChannel('VERTO');
  statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusItem.command = 'verto.pickProfile';

  // Always-visible launcher for the right-side panel (there's no activity-bar icon).
  const panelItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  panelItem.text = '$(zap) VERTO';
  panelItem.tooltip = 'Open the VERTO Pair-Optimizer panel';
  panelItem.command = 'verto.openPanel';
  panelItem.show();
  const cpp: vscode.DocumentSelector = { language: 'cpp', scheme: 'file' };
  const afterProvider: vscode.TextDocumentContentProvider = {
    provideTextDocumentContent: (uri) => afterDocs.get(uri.toString()) ?? '',
  };
  context.subscriptions.push(
    output,
    statusItem,
    panelItem,
    vscode.workspace.registerTextDocumentContentProvider('verto-after', afterProvider),
    vscode.commands.registerCommand('verto.optimizeFile', runOptimize),
    vscode.commands.registerCommand('verto.pickProfile', pickProfile),
    vscode.commands.registerCommand('verto.apply', applyFinding),
    vscode.commands.registerCommand('verto.showDiff', showDiff),
    vscode.commands.registerCommand('verto.showProof', showProof),
    vscode.window.onDidChangeActiveTextEditor(updateStatus),
    vscode.languages.registerCodeLensProvider(cpp, new VertoCodeLensProvider()),
    vscode.languages.registerHoverProvider(cpp, new VertoHoverProvider()),
    vscode.languages.registerCodeActionsProvider(cpp, new VertoCodeActionProvider(), {
      providedCodeActionKinds: [vscode.CodeActionKind.RefactorRewrite],
    }),
  );

  // The hybrid chat+console panel (the locked UX direction) — a webview that opens
  // in the editor column to the RIGHT of the code, and can be reopened by command.
  registerAfterProvider(context);
  context.subscriptions.push(
    vscode.commands.registerCommand('verto.openPanel', () => VertoPanel.createOrShow(context.extensionUri)),
  );
  VertoPanel.createOrShow(context.extensionUri); // auto-open on the right

  updateStatus();
}

export function deactivate(): void {
  /* nothing to clean up */
}

async function runOptimize(): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.document.languageId !== 'cpp') {
    vscode.window.showWarningMessage('VERTO: open a C++ file first.');
    return;
  }
  const uri = editor.document.uri;
  const cfg = vscode.workspace.getConfiguration('verto');
  const command = cfg.get<string>('command', 'verto');
  const compileCommands = cfg.get<string>('compileCommands', '');

  // Flags come from the chosen .verto.json profile; the verto.args setting is the
  // fallback when there's no profile. Structural flags (--json) are always added,
  // and unset policy still falls through to .verto.toml.
  const profiles = loadProfiles(uri);
  const userArgs = core.profileArgs(profiles, activeProfile, cfg.get<string[]>('args', []));
  const args = ['optimize', uri.fsPath, '--json', '--no-daemon', ...userArgs];
  if (compileCommands && !userArgs.includes('-p')) {
    args.push('-p', compileCommands);
  }

  await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: 'VERTO: verifying…', cancellable: false },
    async () => {
      try {
        const stdout = await run(command, args, uri);
        allVerdicts = core.parseReport(stdout);
        findings = core.acceptedFindings(allVerdicts);
        resultUri = uri.toString();
        ran.add(resultUri);
        report(uri, allVerdicts);
        lensChanged.fire();
        vscode.window.showInformationMessage(
          findings.length > 0
            ? `VERTO — ${findings.length} verified optimization(s). Hover a ⚡ lens for the proof.`
            : 'VERTO — nothing cleared the correct-and-faster bar. See the VERTO output for what was tried.',
        );
      } catch (err) {
        vscode.window.showErrorMessage(`VERTO failed: ${err instanceof Error ? err.message : String(err)}`);
      }
    },
  );
}

/** Pick a run profile from .verto.json (the team-shared flag-sets). */
async function pickProfile(): Promise<void> {
  const uri = vscode.window.activeTextEditor?.document.uri;
  const cfg = uri ? loadProfiles(uri) : undefined;
  if (!cfg || Object.keys(cfg.profiles).length === 0) {
    vscode.window.showInformationMessage(
      'VERTO: no .verto.json profiles found. Add one at the repo root to define flag-sets.',
    );
    return;
  }
  const items = Object.entries(cfg.profiles).map(([name, p]) => ({
    label: name,
    description: name === cfg.default ? '(default)' : '',
    detail: p.description ?? p.args.join(' '),
  }));
  const chosen = await vscode.window.showQuickPick(items, { placeHolder: 'VERTO: select an optimization profile' });
  if (chosen) {
    activeProfile = chosen.label;
    updateStatus();
    vscode.window.showInformationMessage(`VERTO — profile "${chosen.label}" selected. Run "Verify & Optimize" to use it.`);
  }
}

/** Honest silence: log accepted + everything that didn't make the cut, and why. */
function report(uri: vscode.Uri, verdicts: core.Verdict[]): void {
  const rel = vscode.workspace.asRelativePath(uri);
  output.appendLine(`── VERTO · ${rel} ──`);
  const accepted = core.acceptedFindings(verdicts);
  output.appendLine(`  ${accepted.length} verified optimization(s):`);
  for (const v of accepted) {
    output.appendLine(`    ✓ ${v.candidate?.transform ?? '?'}  ${core.speedupLabel(v)}  (Rung ${v.correctness?.rung ?? '?'})`);
  }
  const rest = core.nonAcceptedShown(verdicts);
  if (rest.length > 0) {
    output.appendLine(`  not accepted (proven, not hidden):`);
    for (const v of rest) {
      output.appendLine(`    · ${core.outcomeLine(v)}`);
    }
  }
  output.appendLine('');
}

/** Spawn the verto CLI and resolve its stdout (the --json payload). */
function run(command: string, args: string[], uri: vscode.Uri): Promise<string> {
  return new Promise((resolve, reject) => {
    const parts = command.trim().split(/\s+/);
    const bin = parts[0];
    const cwd = vscode.workspace.getWorkspaceFolder(uri)?.uri.fsPath;
    const proc = cp.spawn(bin, [...parts.slice(1), ...args], { cwd });
    let out = '';
    let err = '';
    proc.stdout.on('data', (d) => (out += d.toString()));
    proc.stderr.on('data', (d) => (err += d.toString()));
    proc.on('error', reject);
    // verto exits 0/1/3 (found/none/rejected) — a non-zero code is normal, so we
    // key on getting a JSON payload, not the exit code.
    proc.on('close', () => (out.trim() ? resolve(out) : reject(new Error(err.trim() || 'no output'))));
  });
}

/** The document the current findings belong to (works even when the panel has focus). */
async function targetDoc(): Promise<vscode.TextDocument | undefined> {
  if (!resultUri) {
    return undefined;
  }
  const open = vscode.workspace.textDocuments.find((d) => d.uri.toString() === resultUri);
  return open ?? (await vscode.workspace.openTextDocument(vscode.Uri.parse(resultUri)));
}

async function applyFinding(v: core.Verdict): Promise<void> {
  const doc = await targetDoc();
  if (!doc) {
    return;
  }
  const hunks = core.parseHunks(v.udiff || v.diff || '').sort((a, b) => b.oldStart - a.oldStart);
  if (hunks.length === 0) {
    vscode.window.showWarningMessage('VERTO: no diff to apply for this finding.');
    return;
  }
  const edit = new vscode.WorkspaceEdit();
  for (const h of hunks) {
    const start = h.oldStart - 1;
    const end = Math.min(start + h.oldCount, doc.lineCount);
    edit.replace(doc.uri, new vscode.Range(start, 0, end, 0), h.newLines.join('\n') + '\n');
  }
  if (await vscode.workspace.applyEdit(edit)) {
    findings = findings.filter((f) => f !== v);
    lensChanged.fire();
    vscode.window.showInformationMessage(
      `VERTO — applied ${core.speedupLabel(v)} (${v.candidate?.transform ?? 'change'}).`,
    );
  }
}

/** Open the styled proof panel (the Webview) for a finding. */
function showProof(v: core.Verdict): void {
  if (!resultUri) {
    return;
  }
  panel.showProof(v, vscode.Uri.parse(resultUri), { apply: applyFinding, showDiff });
}

/** Native side-by-side diff: current file vs the VERTO-applied version. */
async function showDiff(v: core.Verdict): Promise<void> {
  const doc = await targetDoc();
  if (!doc) {
    return;
  }
  const after = core.applyUdiff(doc.getText(), v.udiff || v.diff || '');
  // A verto-after: URI whose path keeps the .cpp extension → C++ highlighting on the right.
  const afterUri = doc.uri.with({ scheme: 'verto-after', query: `v${diffSeq++}` });
  afterDocs.set(afterUri.toString(), after);
  const title = `${doc.uri.path.split('/').pop()} ↔ VERTO (${core.speedupLabel(v)})`;
  await vscode.commands.executeCommand('vscode.diff', doc.uri, afterUri, title, { preview: true });
}

class VertoCodeLensProvider implements vscode.CodeLensProvider {
  readonly onDidChangeCodeLenses = lensChanged.event;

  provideCodeLenses(document: vscode.TextDocument): vscode.CodeLens[] {
    const key = document.uri.toString();
    const top = new vscode.Range(0, 0, 0, 0);

    // Two-state: before results (or after a no-win run) show the invitation lens.
    if (key !== resultUri || findings.length === 0) {
      const title = ran.has(key)
        ? '⚡ VERTO — no verified win last run · re-verify this file'
        : '⚡ VERTO — verify & optimize this file';
      return [new vscode.CodeLens(top, { title, command: 'verto.optimizeFile' })];
    }

    // After results: a verified verdict per finding, each with Apply + Show diff.
    const lenses: vscode.CodeLens[] = [];
    for (const v of findings) {
      const line = Math.max(0, core.anchorLine(v) - 1);
      const range = new vscode.Range(line, 0, line, 0);
      const rung = v.correctness?.rung ?? '?';
      lenses.push(
        new vscode.CodeLens(range, {
          title: `⚡ VERTO — verified ${core.speedupLabel(v)} · Rung ${rung}`,
          command: 'verto.showProof',
          arguments: [v],
        }),
        new vscode.CodeLens(range, { title: 'Apply', command: 'verto.apply', arguments: [v] }),
        new vscode.CodeLens(range, { title: 'Diff', command: 'verto.showDiff', arguments: [v] }),
      );
    }
    return lenses;
  }
}

class VertoHoverProvider implements vscode.HoverProvider {
  provideHover(document: vscode.TextDocument, position: vscode.Position): vscode.Hover | undefined {
    if (document.uri.toString() !== resultUri) {
      return undefined;
    }
    const v = findings.find((f) => core.coversLine(f, position.line + 1));
    if (!v) {
      return undefined;
    }
    const md = new vscode.MarkdownString(core.proofMarkdown(v));
    md.isTrusted = true;
    return new vscode.Hover(md);
  }
}

class VertoCodeActionProvider implements vscode.CodeActionProvider {
  provideCodeActions(): vscode.CodeAction[] {
    const action = new vscode.CodeAction('VERTO: Verify & Optimize this file', vscode.CodeActionKind.RefactorRewrite);
    action.command = { command: 'verto.optimizeFile', title: 'VERTO: Verify & Optimize Current File' };
    return [action];
  }
}
