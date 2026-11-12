import fs from "node:fs";
import path from "node:path";

export default function globalSetup() {
  fs.rmSync(path.join(__dirname, ".auth.json"), { force: true });
}
