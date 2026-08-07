const MOCK_HEALTH = Object.freeze({
  status: "ok",
  local_environment: {
    python_available: true,
    python_version: "Python 3.11.9 (browser mock)",
    pymupdf4llm_available: true,
    pymupdf4llm_version: "1.28.0 (browser mock)",
    pandoc_available: true,
    pandoc_version: "pandoc 3.10 (browser mock)",
    git_cli_available: true,
    git_version: "git 2.54.0 (browser mock)",
    github_cli_available: true,
    github_cli_version: "gh 2.92.0 (browser mock)",
  },
  build_architecture: "browser_mock_tauri_v2",
  os: "browser",
});

let tauriInvokePromise;

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function validateCommand(command) {
  if (typeof command !== "string" || command.trim().length === 0) {
    throw new TypeError("IPC command must be a non-empty string.");
  }
}

function globalTauriInvoke() {
  const candidate = globalThis.window?.__TAURI__?.core?.invoke;
  return typeof candidate === "function" ? candidate : null;
}

export function isNativeTauri() {
  return Boolean(globalTauriInvoke() || globalThis.window?.__TAURI_INTERNALS__);
}

export function mockResponse(command, payload) {
  validateCommand(command);

  if (command === "check_system_health") {
    return clone(MOCK_HEALTH);
  }

  return {
    status: "ok",
    mock: true,
    command,
    payload: clone(payload ?? null),
    build_architecture: "browser_mock_tauri_v2",
  };
}

export async function invokeCommand(command, payload) {
  validateCommand(command);

  const directInvoke = globalTauriInvoke();
  if (directInvoke) {
    return directInvoke(command, payload);
  }

  if (globalThis.window?.__TAURI_INTERNALS__) {
    tauriInvokePromise ??= import("@tauri-apps/api/core").then(({ invoke }) => invoke);
    const tauriInvoke = await tauriInvokePromise;
    return tauriInvoke(command, payload);
  }

  console.info("[Mock IPC Call]", { command, payload: payload ?? null });
  return mockResponse(command, payload);
}
