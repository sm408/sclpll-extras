import * as cp from "node:child_process";
import * as vscode from "vscode";
import { LanguageClient, LanguageClientOptions, ServerOptions, State, Trace } from "vscode-languageclient/node";
import { discoverPython, supportsLanguageServer } from "./serverDiscovery";

export class SclplClient {
  private client: LanguageClient | undefined;
  private stateSubscription: vscode.Disposable | undefined;
  private shownUnavailable = false;
  private retries = 0;
  private intentionallyStopped = false;
  constructor(private readonly output: vscode.OutputChannel) {}

  async start(): Promise<void> {
    await this.stop();
    this.intentionallyStopped = false;
    const python = discoverPython();
    if (!python) return this.unavailable();
    if (!supportsLanguageServer(python)) {
      this.output.appendLine(`SCLPL language server dependencies are unavailable in ${python}.`);
      return this.unavailable();
    }
    const serverOptions: ServerOptions = async () => {
      const args = python === "py" ? ["-3", "-m", "sclpll_language_server", "--stdio"] : ["-m", "sclpll_language_server", "--stdio"];
      const process = cp.spawn(python, args, { cwd: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath, windowsHide: true });
      process.stderr.on("data", value => this.output.append(value.toString()));
      process.on("error", error => { this.output.appendLine(`Server launch error: ${error.message}`); void this.unavailable(); });
      return process;
    };
    const options: LanguageClientOptions = {
      documentSelector: [{ language: "sclpll", scheme: "file" }],
      outputChannel: this.output,
      initializationOptions: {
        diagnostics: vscode.workspace.getConfiguration("sclpl").get<boolean>("diagnostics.enable", true),
        semanticHighlighting: vscode.workspace.getConfiguration("sclpl").get<boolean>("semanticHighlighting.enable", true),
      },
    };
    this.client = new LanguageClient("sclpl", "SCLPL Language Server", serverOptions, options);
    const trace = vscode.workspace.getConfiguration("sclpl").get<string>("trace.server");
    this.client.setTrace(trace === "verbose" ? Trace.Verbose : trace === "messages" ? Trace.Messages : Trace.Off);
    this.stateSubscription = this.client.onDidChangeState(event => {
      if (event.newState === State.Stopped && !this.intentionallyStopped) this.retryAfterCrash();
    });
    try { await this.client.start(); this.retries = 0; this.output.appendLine(`Started SCLPL language server with ${python}.`); }
    catch (error) { this.output.appendLine(`Server unavailable: ${String(error)}`); await this.unavailable(); }
  }

  async stop(): Promise<void> {
    this.intentionallyStopped = true;
    this.stateSubscription?.dispose(); this.stateSubscription = undefined;
    if (this.client) {
      try { await this.client.stop(); }
      catch (error) { this.output.appendLine(`Server shutdown note: ${String(error)}`); }
      finally { this.client = undefined; }
    }
  }
  async restart(): Promise<void> { this.shownUnavailable = false; await this.start(); }
  private retryAfterCrash(): void {
    if (this.retries >= 3) { this.output.appendLine("Language server stopped after three restart attempts."); void this.unavailable(); return; }
    this.retries += 1;
    this.output.appendLine(`Language server stopped unexpectedly; retrying (${this.retries}/3).`);
    setTimeout(() => void this.start(), 500 * this.retries);
  }
  private async unavailable(): Promise<void> {
    if (this.shownUnavailable) return;
    this.shownUnavailable = true;
    const action = await vscode.window.showWarningMessage("SCLPLL language server is unavailable in this Python environment. From sclpll-extras, run: pip install -e language-server", "Retry", "Select Python");
    if (action === "Retry") await this.restart();
    if (action === "Select Python") await vscode.commands.executeCommand("python.setInterpreter");
  }
}
