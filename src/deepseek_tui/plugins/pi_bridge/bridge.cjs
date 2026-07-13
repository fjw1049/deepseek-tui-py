#!/usr/bin/env node
/**
 * DeepSeek Pi extension bridge — NDJSON JSON-RPC over stdio.
 *
 * Loads package entrypoints with a minimal ExtensionAPI shim that collects
 * tools/commands. This is intentionally a tracer-bullet host, not a full Pi
 * TUI/runtime clone. TypeScript entrypoints require the host to spawn Node
 * with ``--experimental-strip-types`` (Node 22.6+).
 */
"use strict";

const fs = require("fs");
const path = require("path");
const { pathToFileURL } = require("url");
const readline = require("readline");

const state = {
  packageRoot: "",
  cwd: process.cwd(),
  tools: new Map(),
  commands: new Map(),
  handlers: new Map(),
  started: false,
};

function createApi() {
  const api = {
    registerTool(def) {
      if (!def || typeof def.name !== "string") {
        throw new Error("registerTool requires { name }");
      }
      state.tools.set(def.name, def);
    },
    registerCommand(name, options = {}) {
      const key = typeof name === "string" ? name : name && name.name;
      if (!key) throw new Error("registerCommand requires a name");
      const opts = typeof name === "string" ? options : name;
      state.commands.set(key, opts || {});
    },
    on(event, handler) {
      if (typeof event !== "string" || typeof handler !== "function") return;
      const list = state.handlers.get(event) || [];
      list.push(handler);
      state.handlers.set(event, list);
    },
    off(event, handler) {
      if (typeof event !== "string") return;
      const list = state.handlers.get(event) || [];
      state.handlers.set(
        event,
        typeof handler === "function" ? list.filter((fn) => fn !== handler) : []
      );
    },
    sendUserMessage() {},
    sendSystemMessage() {},
    appendEntry() {},
    setStatus() {},
    notify() {},
    getActiveTools() {
      return [...state.tools.keys()];
    },
    getAllTools() {
      return [...state.tools.values()].map(toolDescriptor);
    },
    setActiveTools() {},
    getContext() {
      return { cwd: state.cwd, packageRoot: state.packageRoot };
    },
    getCwd() {
      return state.cwd;
    },
    ui: {
      notify() {},
      select: async () => null,
      confirm: async () => false,
      input: async () => "",
    },
  };
  return api;
}

function toolDescriptor(def) {
  return {
    name: def.name,
    label: def.label || def.name,
    description: def.description || "",
    inputSchema: toJsonSchema(def.parameters),
  };
}

function toJsonSchema(parameters) {
  if (!parameters) return { type: "object", properties: {} };
  if (typeof parameters === "object" && parameters.type) return parameters;
  // TypeBox schemas are already JSON-Schema shaped in practice.
  if (typeof parameters === "object") return parameters;
  return { type: "object", properties: {} };
}

async function emit(event, payload) {
  const list = state.handlers.get(event) || [];
  for (const handler of list) {
    try {
      const maybe = handler(payload);
      if (maybe && typeof maybe.then === "function") await maybe;
    } catch {
      // Extension handlers must not crash the bridge.
    }
  }
}

async function loadEntrypoint(entry) {
  const absolute = path.resolve(state.packageRoot, entry);
  let target = absolute;
  const stat = fs.existsSync(absolute) ? fs.statSync(absolute) : null;
  if (stat && stat.isDirectory()) {
    for (const name of ["index.mjs", "index.js", "index.cjs", "index.ts"]) {
      const candidate = path.join(absolute, name);
      if (fs.existsSync(candidate)) {
        target = candidate;
        break;
      }
    }
  }
  if (!fs.existsSync(target)) {
    throw new Error(`entrypoint not found: ${entry}`);
  }
  if (target.endsWith(".ts") || target.endsWith(".tsx")) {
    // Host must spawn with --experimental-strip-types; surface a clear error
    // when that flag was omitted.
    if (!process.execArgv.some((arg) => arg.includes("experimental-strip-types"))) {
      throw new Error(
        `TypeScript entrypoint requires --experimental-strip-types: ${entry}`
      );
    }
  }
  const mod = await import(pathToFileURL(target).href);
  const factory = mod.default || mod;
  if (typeof factory !== "function") {
    throw new Error(`entrypoint did not export a default function: ${entry}`);
  }
  const api = createApi();
  const maybePromise = factory(api);
  if (maybePromise && typeof maybePromise.then === "function") {
    await maybePromise;
  }
}

async function handle(method, params) {
  switch (method) {
    case "initialize": {
      state.packageRoot = path.resolve(String(params.packageRoot || ""));
      state.cwd = path.resolve(String(params.cwd || state.packageRoot));
      state.tools.clear();
      state.commands.clear();
      state.handlers.clear();
      const entries = Array.isArray(params.entrypoints) ? params.entrypoints : [];
      for (const entry of entries) {
        await loadEntrypoint(String(entry));
      }
      state.started = true;
      await emit("session_start", { cwd: state.cwd });
      return {
        protocolVersion: 1,
        tools: state.tools.size,
        commands: state.commands.size,
        stripTypes: process.execArgv.some((arg) =>
          arg.includes("experimental-strip-types")
        ),
      };
    }
    case "tools/list":
      ensureStarted();
      return { tools: [...state.tools.values()].map(toolDescriptor) };
    case "tools/call": {
      ensureStarted();
      const name = String(params.name || "");
      const tool = state.tools.get(name);
      if (!tool) throw new Error(`unknown tool: ${name}`);
      const args = params.arguments || {};
      const result = await tool.execute(
        params.callId || "call",
        args,
        undefined,
        undefined,
        { cwd: state.cwd, ui: createApi().ui }
      );
      return normalizeResult(result);
    }
    case "commands/list":
      ensureStarted();
      return {
        commands: [...state.commands.entries()].map(([name, opts]) => ({
          name,
          description: (opts && opts.description) || "",
        })),
      };
    case "commands/call": {
      ensureStarted();
      const name = String(params.name || "");
      const command = state.commands.get(name);
      if (!command || typeof command.handler !== "function") {
        throw new Error(`unknown command: ${name}`);
      }
      await command.handler(String(params.args || ""), {
        cwd: state.cwd,
        ui: createApi().ui,
      });
      return { ok: true };
    }
    case "lifecycle/session_start":
      ensureStarted();
      await emit("session_start", { cwd: state.cwd });
      return { ok: true };
    case "lifecycle/session_shutdown":
      ensureStarted();
      await emit("session_shutdown", { cwd: state.cwd });
      return { ok: true };
    case "shutdown":
      await emit("shutdown", {});
      return { ok: true };
    default:
      throw new Error(`method not found: ${method}`);
  }
}

function ensureStarted() {
  if (!state.started) throw new Error("bridge not initialized");
}

function normalizeResult(result) {
  if (!result || typeof result !== "object") {
    return { content: [{ type: "text", text: String(result ?? "") }], details: {} };
  }
  const content = Array.isArray(result.content)
    ? result.content
    : [{ type: "text", text: String(result.text ?? "") }];
  return { content, details: result.details || {} };
}

function respond(id, result, error) {
  const message = error
    ? { jsonrpc: "2.0", id, error: { code: -32000, message: String(error.message || error) } }
    : { jsonrpc: "2.0", id, result };
  process.stdout.write(JSON.stringify(message) + "\n");
}

const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
rl.on("line", async (line) => {
  let message;
  try {
    message = JSON.parse(line);
  } catch (err) {
    respond(null, null, err);
    return;
  }
  if (!message || message.jsonrpc !== "2.0" || typeof message.method !== "string") {
    respond(message && message.id, null, new Error("invalid JSON-RPC request"));
    return;
  }
  try {
    const result = await handle(message.method, message.params || {});
    respond(message.id ?? null, result);
    if (message.method === "shutdown") {
      rl.close();
      process.exit(0);
    }
  } catch (err) {
    respond(message.id ?? null, null, err);
  }
});
