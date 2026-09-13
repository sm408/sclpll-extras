import * as assert from "node:assert/strict";
import * as vscode from "vscode";

function wait(milliseconds: number): Promise<void> { return new Promise(resolve => setTimeout(resolve, milliseconds)); }

suite("SCLPL extension", () => {
  test("recognizes SCLPLL and supplies live server completion", async function () {
    this.timeout(30_000);
    const extension = vscode.extensions.getExtension("sclpl-local.sclpl-language-tools");
    assert.ok(extension, "extension should be discoverable");
    const python = process.env.SCLPL_TEST_PYTHON;
    if (python) await vscode.workspace.getConfiguration("sclpl").update("pythonPath", python, vscode.ConfigurationTarget.Workspace);
    await extension.activate();
    const document = await vscode.workspace.openTextDocument(vscode.Uri.joinPath(extension.extensionUri, "test", "fixtures", "showcase.sclpll"));
    await vscode.window.showTextDocument(document);
    assert.equal(document.languageId, "sclpll");
    // The asset/recognition test must be runnable with only the extension
    // installed. CI supplies this opt-in interpreter to exercise the real
    // server; a developer without sclpl[editor] still gets a useful fallback
    // test and the extension's missing-server UX.
    if (!python) return;
    for (let attempt = 0; attempt < 20; attempt += 1) {
      const result = await vscode.commands.executeCommand<vscode.CompletionList | vscode.CompletionItem[]>("vscode.executeCompletionItemProvider", document.uri, new vscode.Position(0, 0));
      if (result && (Array.isArray(result) ? result.length : result.items.length)) return;
      await wait(250);
    }
    assert.fail("SCLPL language server did not register a completion provider");
  });
});
