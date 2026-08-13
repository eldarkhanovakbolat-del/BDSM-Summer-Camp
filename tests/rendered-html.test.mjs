import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { readFile } from "node:fs/promises";
import net from "node:net";
import test from "node:test";
import { fileURLToPath } from "node:url";

async function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close((error) => (error ? reject(error) : resolve(port)));
    });
  });
}

async function render() {
  const port = await freePort();
  const cli = new URL("../node_modules/vinext/dist/cli.js", import.meta.url);
  const child = spawn(process.execPath, [fileURLToPath(cli), "start", "--hostname", "127.0.0.1", "--port", String(port)], {
    cwd: fileURLToPath(new URL("..", import.meta.url)),
    env: { ...process.env, NODE_ENV: "production" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let failure = "";
  child.stderr.on("data", (chunk) => { failure += chunk; });
  try {
    for (let attempt = 0; attempt < 80; attempt += 1) {
      if (child.exitCode !== null) throw new Error(failure || `vinext exited with ${child.exitCode}`);
      try {
        const response = await fetch(`http://127.0.0.1:${port}/`, { headers: { accept: "text/html" } });
        return {
          status: response.status,
          contentType: response.headers.get("content-type") ?? "",
          html: await response.text(),
        };
      } catch {
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
    }
    throw new Error(`vinext did not start: ${failure}`);
  } finally {
    child.kill();
  }
}

test("renders the BDSM Summer Camp product shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.contentType, /^text\/html\b/i);
  const html = response.html;
  assert.match(html, /<title>BDSM 夏令营<\/title>/);
  assert.match(html, /完整选课目录/);
  assert.match(html, /BDSM 101/);
  assert.match(html, /Theory/);
  assert.match(html, /Disciplines/);
});

test("ships the checked wiki catalog and all user controls", async () => {
  const [catalogRaw, appSource, proxySource] = await Promise.all([
    readFile(new URL("../server/wiki_catalog.json", import.meta.url), "utf8"),
    readFile(new URL("../app/ExperienceApp.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/api/[...path]/route.ts", import.meta.url), "utf8"),
  ]);
  const catalog = JSON.parse(catalogRaw);
  const counts = Object.fromEntries(catalog.sections.map((section) => [section.id, section.unique_count]));
  assert.deepEqual(counts, { bdsm101: 25, theory: 85, disciplines: 268 });
  assert.match(appSource, /AI 名称/);
  assert.match(appSource, /留空时只显示/);
  assert.match(appSource, /← 返回选课目录/);
  assert.doesNotMatch(appSource, /返回 Memory/);
  assert.match(appSource, /说话/);
  assert.match(appSource, /行动/);
  assert.match(appSource, /想法/);
  assert.match(appSource, /提问/);
  assert.match(appSource, /OOC/);
  assert.match(appSource, /project-logo\.png/);
  assert.match(proxySource, /CAMP_SERVER_URL/);
  assert.doesNotMatch(proxySource, /AI_API_KEY/);
});
