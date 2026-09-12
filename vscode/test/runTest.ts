import * as path from "node:path";
import { runTests } from "@vscode/test-electron";

async function main(): Promise<void> {
  const extensionDevelopmentPath = process.env.SCLPL_TEST_EXTENSION_PATH ?? path.resolve(__dirname, "../..");
  const extensionTestsPath = path.resolve(extensionDevelopmentPath, "out", "test", "suite", "index");
  const workspace = path.resolve(extensionDevelopmentPath, "test/fixtures");
  await runTests({
    extensionDevelopmentPath,
    extensionTestsPath,
    launchArgs: [workspace, "--disable-workspace-trust"],
    vscodeExecutablePath: process.env.VSCODE_EXECUTABLE,
    extensionTestsEnv: { SCLPL_TEST_PYTHON: process.env.SCLPL_TEST_PYTHON },
  });
}

void main().catch(error => { console.error(error); process.exit(1); });
