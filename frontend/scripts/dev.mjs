import { spawn } from "node:child_process";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { existsSync } from "node:fs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(__dirname, "..");
const repoRoot = path.resolve(frontendDir, "..");
const backendDir = path.join(repoRoot, "backend");
const apiBase = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

function parseLocalApiTarget() {
  let url;
  try {
    url = new URL(apiBase);
  } catch {
    return null;
  }
  const localHosts = new Set(["localhost", "127.0.0.1", "::1"]);
  if (!localHosts.has(url.hostname)) return null;
  return {
    host: url.hostname === "::1" ? "::1" : "127.0.0.1",
    port: Number(url.port || (url.protocol === "https:" ? 443 : 80)),
  };
}

function canConnect(host, port, timeoutMs = 500) {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host, port });
    const done = (ok) => {
      socket.removeAllListeners();
      socket.destroy();
      resolve(ok);
    };
    socket.setTimeout(timeoutMs);
    socket.once("connect", () => done(true));
    socket.once("timeout", () => done(false));
    socket.once("error", () => done(false));
  });
}

async function waitForApi(url, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${url.replace(/\/$/, "")}/health`, { cache: "no-store" });
      if (response.ok) return true;
    } catch {
      // Keep waiting while the API boots.
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return false;
}

function spawnProcess(command, args, options) {
  return spawn(command, args, {
    stdio: "inherit",
    shell: false,
    ...options,
  });
}

function canStartBackend() {
  return existsSync(backendDir) && existsSync(path.join(backendDir, ".venv", "bin", "uvicorn"));
}

function warnBackendUnavailable() {
  console.warn(`[varsten-dev] API is not listening at ${apiBase}.`);
  console.warn("[varsten-dev] Start it separately with: cd backend && .venv/bin/uvicorn app.main:app --reload");
}

function startBackend(target) {
  console.log(`[varsten-dev] Starting API at ${apiBase}`);
  return spawnProcess(
    path.join(backendDir, ".venv", "bin", "uvicorn"),
    ["app.main:app", "--reload", "--host", "0.0.0.0", "--port", String(target.port)],
    {
      cwd: backendDir,
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
    },
  );
}

async function warnIfApiNotReady() {
  const ready = await waitForApi(apiBase);
  if (!ready) {
    console.warn(`[varsten-dev] API did not answer ${apiBase}/health yet. Keeping logs attached while Next starts.`);
  }
}

async function ensureBackend() {
  const target = parseLocalApiTarget();
  if (!target) return null;

  if (await canConnect(target.host, target.port)) {
    console.log(`[varsten-dev] API already listening at ${apiBase}`);
    return null;
  }

  if (!canStartBackend()) {
    warnBackendUnavailable();
    return null;
  }

  const backend = startBackend(target);
  await warnIfApiNotReady();
  return backend;
}

function startNext() {
  const nextBin = process.platform === "win32" ? "next.cmd" : "next";
  const args = ["dev", ...process.argv.slice(2)];
  return spawnProcess(nextBin, args, { cwd: frontendDir, env: process.env });
}

const backend = await ensureBackend();
const next = startNext();

function shutdown(signal) {
  if (backend && !backend.killed) backend.kill(signal);
  if (!next.killed) next.kill(signal);
}

process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));

next.on("exit", (code, signal) => {
  if (backend && !backend.killed) backend.kill("SIGTERM");
  if (signal) process.kill(process.pid, signal);
  process.exit(code ?? 0);
});
