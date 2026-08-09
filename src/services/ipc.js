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
let nextMockBatchId = 0;
let mockQueue = emptyQueue();

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function emptyQueue() {
  return {
    batchId: 0,
    status: "idle",
    total: 0,
    completed: 0,
    cancelRequested: false,
    items: [],
  };
}

function validateCommand(command) {
  if (typeof command !== "string" || command.trim().length === 0) {
    throw new TypeError("IPC command must be a non-empty string.");
  }
}

function validateBatchRequest(request) {
  if (!request || typeof request !== "object" || Array.isArray(request)) {
    throw new TypeError("Batch request must be an object.");
  }
  if (!Array.isArray(request.files) || request.files.length === 0) {
    throw new TypeError("Batch request must include at least one file.");
  }
  if (!request.files.every((file) => typeof file === "string" && file.trim())) {
    throw new TypeError("Batch request files must be non-empty strings.");
  }
  if (typeof request.outputDirectory !== "string" || !request.outputDirectory.trim()) {
    throw new TypeError("Batch request must include an outputDirectory.");
  }
}

const MOCK_SUPPORTED_EXTENSIONS = ["pdf", "docx", "txt"];

function mockOutputPath(sourcePath, outputDirectory, reserved) {
  const sourceName = sourcePath.split(/[\\/]/).at(-1) || "document";
  const stem = (sourceName.replace(/\.[^.]*$/, "") || "document").replace(/[<>:"/\\|?*]/g, "");
  const safeStem = stem.trim().replace(/[. ]+$/g, "") || "document";
  let index = 0;
  while (true) {
    const suffix = index === 0 ? "" : `_${index}`;
    const candidate = `${safeStem}${suffix}.md`;
    if (!reserved.has(candidate.toLowerCase())) {
      reserved.add(candidate.toLowerCase());
      return `${outputDirectory.replace(/[\\/]$/, "")}/${candidate}`;
    }
    index += 1;
  }
}

function mockExtension(sourcePath) {
  const sourceName = sourcePath.split(/[\\/]/).at(-1) || "";
  return (sourceName.includes(".") ? sourceName.slice(sourceName.lastIndexOf(".") + 1) : "").toLowerCase();
}

function mockStartBatch(payload) {
  const request = payload?.request;
  validateBatchRequest(request);
  if (mockQueue.status === "running") {
    throw new Error("a conversion batch is already running");
  }
  const reserved = new Set();
  mockQueue = {
    batchId: ++nextMockBatchId,
    status: "running",
    total: request.files.length,
    completed: 0,
    cancelRequested: false,
    items: request.files.map((sourcePath) => ({
      sourcePath,
      outputPath: MOCK_SUPPORTED_EXTENSIONS.includes(mockExtension(sourcePath))
        ? mockOutputPath(sourcePath, request.outputDirectory, reserved)
        : null,
      status: "queued",
      error: null,
      characters: null,
      elapsedSeconds: null,
    })),
  };
  return clone(mockQueue);
}

function mockCancelBatch() {
  if (mockQueue.status === "running") {
    let completed = mockQueue.completed;
    mockQueue = {
      ...mockQueue,
      cancelRequested: true,
      items: mockQueue.items.map((item) => {
        if (item.status !== "queued") return item;
        completed += 1;
        return { ...item, status: "cancelled" };
      }),
    };
    mockQueue.completed = completed;
    mockQueue.status = "cancelled";
  }
  return clone(mockQueue);
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

  if (command === "check_system_health") return clone(MOCK_HEALTH);
  if (command === "start_conversion_batch") return mockStartBatch(payload);
  if (command === "cancel_batch") return mockCancelBatch();
  if (command === "get_queue_status") return clone(mockQueue);

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
  if (directInvoke) return directInvoke(command, payload);

  if (globalThis.window?.__TAURI_INTERNALS__) {
    tauriInvokePromise ??= import("@tauri-apps/api/core").then(({ invoke }) => invoke);
    const tauriInvoke = await tauriInvokePromise;
    return tauriInvoke(command, payload);
  }

  console.info("[Mock IPC Call]", { command, payload: payload ?? null });
  return mockResponse(command, payload);
}

export function startConversionBatch(request) {
  validateBatchRequest(request);
  return invokeCommand("start_conversion_batch", { request });
}

export function cancelBatch() {
  return invokeCommand("cancel_batch");
}

export function getQueueStatus() {
  return invokeCommand("get_queue_status");
}

export function checkSystemHealth() {
  return invokeCommand("check_system_health");
}
