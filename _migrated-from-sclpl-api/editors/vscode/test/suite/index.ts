import Mocha from "mocha";
import * as path from "node:path";

export function run(): Promise<void> {
  const mocha = new Mocha({ ui: "tdd", color: true });
  mocha.addFile(path.resolve(__dirname, "extension.test.js"));
  return new Promise((resolve, reject) => mocha.run((failures: number) => failures ? reject(new Error(`${failures} extension-host tests failed`)) : resolve()));
}
