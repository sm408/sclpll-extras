import * as cp from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";
import * as vscode from "vscode";

export function discoverPython(): string | undefined {
  const configured = vscode.workspace.getConfiguration("sclpl").get<string>("pythonPath")?.trim();
  if (configured) return configured;
  // This setting is contributed by the Python extension, but reading it does not
  // require that extension. It lets SCLPL follow a workspace's selected interpreter.
  const selected = vscode.workspace.getConfiguration("python").get<string>("defaultInterpreterPath")?.trim();
  if (selected && fs.existsSync(selected)) return selected;
  const workspace = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  if (workspace) {
    const candidate = process.platform === "win32"
      ? path.join(workspace, ".venv", "Scripts", "python.exe")
      : path.join(workspace, ".venv", "bin", "python");
    if (fs.existsSync(candidate)) return candidate;
  }
  return process.platform === "win32" ? "py" : "python3";
}

export function supportsLanguageServer(python: string): boolean {
  const args = python === "py"
    ? ["-3", "-c", "import sclpl, pygls"]
    : ["-c", "import sclpl, pygls"];
  const result = cp.spawnSync(python, args, { windowsHide: true, stdio: "ignore" });
  return result.status === 0 && !result.error;
}
