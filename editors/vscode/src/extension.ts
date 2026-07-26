// VERTO VS Code extension — the editor glue. Registers the "verify & optimize"
// command, a CodeLens over each verified finding, a proof-on-hover, and Apply via
// a WorkspaceEdit. All heavy lifting is the `verto` CLI; this file only renders its
// `--json` Verdicts. Pure logic lives in core.ts.
import * as cp from 'child_process';
import * as vscode from 'vscode';
import * as core from './core';

// Findings for the one document we last verified (MVP scope: current file).
let findings: core.Verdict[] = [];
let findingsUri: string | undefined;
const lensChanged = new vscode.EventEmitter<void>();

export function activate(context: vscode.ExtensionContext): void {
  const cpp: vscode.DocumentSelector = { language: 'cpp', scheme: 'file' };
  context.subscriptions.push(
    vscode.commands.registerCommand('verto.optimizeFile', runOptimize),
    vscode.commands.registerCommand('verto.apply', applyFinding),
    vscode.languages.registerCodeLensProvider(cpp, new VertoCodeLensProvider()),
    vscode.languages.registerHoverProvider(cpp, new VertoHoverProvider()),
  );
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
  const model = cfg.get<string>('model', 'rules');
  const compileCommands = cfg.get<string>('compileCommands', '');

  const args = ['optimize', uri.fsPath, '--json', '--no-daemon', '--model', model];
  if (compileCommands) {
    args.push('-p', compileCommands);
  }

  await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: 'VERTO: verifying…', cancellable: false },
    async () => {
      try {
        const stdout = await run(command, args, uri);
        findings = core.acceptedFindings(core.parseReport(stdout));
        findingsUri = uri.toString();
        lensChanged.fire();
        vscode.window.showInformationMessage(
          findings.length > 0
            ? `VERTO — ${findings.length} verified optimization(s). Hover a ⚡ lens for the proof.`
            : 'VERTO — nothing cleared the correct-and-faster bar this run.',
        );
      } catch (err) {
        vscode.window.showErrorMessage(`VERTO failed: ${err instanceof Error ? err.message : String(err)}`);
      }
    },
  );
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

async function applyFinding(v: core.Verdict): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    return;
  }
  const doc = editor.document;
  const hunks = core.parseHunks(v.udiff || v.diff || '').sort((a, b) => b.oldStart - a.oldStart);
  if (hunks.length === 0) {
    vscode.window.showWarningMessage('VERTO: no diff to apply for this finding.');
    return;
  }
  const edit = new vscode.WorkspaceEdit();
  for (const h of hunks) {
    const start = h.oldStart - 1;
    const end = Math.min(start + h.oldCount, doc.lineCount);
    const range = new vscode.Range(start, 0, end, 0);
    edit.replace(doc.uri, range, h.newLines.join('\n') + '\n');
  }
  if (await vscode.workspace.applyEdit(edit)) {
    findings = findings.filter((f) => f !== v);
    lensChanged.fire();
    vscode.window.showInformationMessage(
      `VERTO — applied ${core.speedupLabel(v)} (${v.candidate?.transform ?? 'change'}).`,
    );
  }
}

class VertoCodeLensProvider implements vscode.CodeLensProvider {
  readonly onDidChangeCodeLenses = lensChanged.event;

  provideCodeLenses(document: vscode.TextDocument): vscode.CodeLens[] {
    if (document.uri.toString() !== findingsUri) {
      return [];
    }
    return findings.map((v) => {
      const line = Math.max(0, core.anchorLine(v) - 1);
      const rung = v.correctness?.rung ?? '?';
      return new vscode.CodeLens(new vscode.Range(line, 0, line, 0), {
        title: `⚡ VERTO — verified ${core.speedupLabel(v)} · Rung ${rung} — Apply`,
        command: 'verto.apply',
        arguments: [v],
      });
    });
  }
}

class VertoHoverProvider implements vscode.HoverProvider {
  provideHover(document: vscode.TextDocument, position: vscode.Position): vscode.Hover | undefined {
    if (document.uri.toString() !== findingsUri) {
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
