import * as fs from "node:fs";
import * as path from "node:path";
import { loadWASM, OnigScanner, OnigString } from "vscode-oniguruma";
import { INITIAL, parseRawGrammar, Registry } from "vscode-textmate";

async function main(): Promise<void> {
  const root = path.resolve(__dirname, "../..");
  for (const item of ["package.json", "language-configuration.json", "syntaxes/sclpll.tmLanguage.json", "snippets/sclpll.json", "src/extension.ts"]) {
    if (!fs.existsSync(path.join(root, item))) throw new Error(`missing extension asset: ${item}`);
  }
  const packageJson = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
  const grammarPath = path.join(root, "syntaxes/sclpll.tmLanguage.json");
  const grammarSource = fs.readFileSync(grammarPath, "utf8");
  const snippets = JSON.parse(fs.readFileSync(path.join(root, "snippets/sclpll.json"), "utf8"));
  if (packageJson.contributes.languages[0].id !== "sclpll") throw new Error("SCLPLL language id is missing");
  if (!packageJson.contributes.languages[0].extensions.includes(".sclpll")) throw new Error(".sclpll is not registered");
  for (const snippet of ["Workflow", "GET step", "Python step", "Foreach", "While", "Conditional", "Parallel", "Gate", "Output writing step"]) {
    if (!(snippet in snippets)) throw new Error(`missing ${snippet} snippet`);
  }

  await loadWASM(fs.readFileSync(require.resolve("vscode-oniguruma/release/onig.wasm")).buffer);
  const registry = new Registry({
    onigLib: Promise.resolve({
      createOnigScanner: (sources: string[]) => new OnigScanner(sources),
      createOnigString: (value: string) => new OnigString(value),
    }),
    loadGrammar: async scopeName => scopeName === "source.sclpll" ? parseRawGrammar(grammarSource, grammarPath) : null,
  });
  const textmate = await registry.loadGrammar("source.sclpll");
  if (!textmate) throw new Error("SCLPLL TextMate grammar did not load");
  const source = [
    '@workflow demo "value" # comment',
    '@input data:json',
    '@step fetch',
    '  get @fetch.status == 200',
    '  retry 3',
  ];
  let state = INITIAL;
  const scopes = new Set<string>();
  for (const line of source) {
    const tokenized = textmate.tokenizeLine(line, state);
    state = tokenized.ruleStack;
    for (const token of tokenized.tokens) token.scopes.forEach(scope => scopes.add(scope));
  }
  for (const scope of [
    "keyword.control.directive.sclpll",
    "string.quoted.double.sclpll",
    "comment.line.number-sign.sclpll",
    "support.type.format.sclpll",
    "keyword.control.http.sclpll",
    "variable.other.reference.sclpll",
    "keyword.other.clause.sclpll",
    "constant.numeric.sclpll",
    "keyword.operator.sclpll",
  ]) {
    if (!scopes.has(scope)) throw new Error(`TextMate grammar did not emit ${scope}`);
  }
  console.log("SCLPL VS Code extension smoke test passed.");
}

void main().catch(error => { console.error(error); process.exit(1); });
