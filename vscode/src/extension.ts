import * as cp from "node:child_process";
import * as vscode from "vscode";
import { SclplClient } from "./languageClient";
import { discoverPython } from "./serverDiscovery";

let client: SclplClient | undefined;

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  const output = vscode.window.createOutputChannel("SCLPL Language Server");
  client = new SclplClient(output);
  context.subscriptions.push(output, { dispose: () => void client?.stop() });
  await client.start();
  context.subscriptions.push(vscode.workspace.onDidChangeConfiguration(event => {
    if (
      event.affectsConfiguration("sclpl.pythonPath") ||
      event.affectsConfiguration("sclpl.trace.server") ||
      event.affectsConfiguration("sclpl.diagnostics.enable") ||
      event.affectsConfiguration("sclpl.semanticHighlighting.enable")
    ) void client?.restart();
  }));
  context.subscriptions.push(
    vscode.commands.registerCommand("sclpl.restartServer", () => client?.restart()),
    vscode.commands.registerCommand("sclpl.showServerOutput", () => output.show(true)),
    vscode.commands.registerCommand("sclpl.format", () => vscode.commands.executeCommand("editor.action.formatDocument")),
    vscode.commands.registerCommand("sclpl.validate", () => runCli("validate", output)),
    vscode.commands.registerCommand("sclpl.run", () => runCli("run", output)),
    vscode.commands.registerCommand("sclpl.explain", () => runCli("explain", output)),
    vscode.commands.registerCommand("sclpl.graph", () => runCli("graph", output, ["--format", "mermaid"]))
  );
}

async function runCli(command: string, output: vscode.OutputChannel, extra: string[] = []): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.document.languageId !== "sclpll") return;
  if (editor.document.isDirty) await editor.document.save();
  const python = discoverPython();
  if (!python) return;
  const args = python === "py" ? ["-3", "-m", "sclpl", command, editor.document.uri.fsPath, ...extra] : ["-m", "sclpl", command, editor.document.uri.fsPath, ...extra];
  output.show(true); output.appendLine(`$ ${python} ${args.join(" ")}`);
  const child = cp.spawn(python, args, { cwd: vscode.workspace.getWorkspaceFolder(editor.document.uri)?.uri.fsPath, windowsHide: true });
  child.stdout.on("data", value => output.append(value.toString()));
  child.stderr.on("data", value => output.append(value.toString()));
  child.on("close", code => output.appendLine(`SCLPL ${command} exited ${code ?? "unknown"}.`));
}

export async function deactivate(): Promise<void> { await client?.stop(); }
