/**
 * Framework-free queue store for the conversion shell.
 *
 * The store owns all domain state (queue items, options, batch lifecycle)
 * and talks to the outside world exclusively through the injected IPC
 * adapter (the exported functions of src/services/ipc.js) so it stays fully
 * deterministically unit-testable without a DOM or a Tauri runtime.
 */

export const SUPPORTED_EXTENSIONS = ["pdf", "docx", "txt"];

export const ITEM_STATUS = Object.freeze({
  QUEUED: "Queued",
  PROCESSING: "Processing",
  COMPLETED: "Completed",
  FAILED: "Failed",
  UNSUPPORTED: "Unsupported",
  CANCELLED: "Cancelled",
});

const PREVIEW_PER_ITEM_MS = 420;
const NATIVE_POLL_MS = 250;

let idCounter = 0;

function nextId() {
  idCounter += 1;
  return `item-${idCounter}`;
}

function extensionOf(path) {
  const name = String(path).split(/[\\/]/).at(-1) ?? "";
  const dot = name.lastIndexOf(".");
  return dot <= 0 ? "" : name.slice(dot + 1).toLowerCase();
}

function baseName(path) {
  return String(path).split(/[\\/]/).at(-1) ?? String(path);
}

function safeStem(path) {
  let stem = baseName(path).replace(/\.[^.]*$/, "");
  stem = stem.replace(/[. ]+$/g, "").trim();
  if (!stem) stem = "document";
  return stem.replace(/[<>:"/\\|?*]/g, "");
}

function parentOf(path) {
  const parts = String(path).split(/[\\/]/);
  parts.pop();
  return parts.length ? parts.join("/") : ".";
}

function initialOptions() {
  return {
    format: "md",
    outputMode: "auto",
    extractImages: "auto",
    outputFolder: "",
  };
}

/**
 * @param {object} adapter IPC adapter surface:
 *   startBatch(request) => queue report
 *   getQueueStatus() => queue report
 *   cancelBatch() => queue report
 *   isNative: boolean
 * @param {object} runtime optional test seams:
 *   delay(ms) -> Promise, pollInterval(ms)
 */
export function createStore(adapter, runtime = {}) {
  const delayImpl = runtime.delay ?? ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
  const pollInterval = runtime.pollInterval ?? NATIVE_POLL_MS;

  let options = initialOptions();
  let items = [];
  let batchStatus = "idle";
  let batchId = null;
  let processing = false;
  let cancelRequested = false;
  const subscribers = new Set();

  function emit() {
    for (const subscriber of subscribers) {
      subscriber(getState());
    }
  }

  function subscribe(listener) {
    subscribers.add(listener);
    return () => subscribers.delete(listener);
  }

  function getState() {
    return {
      options: { ...options },
      items: items.map((item) => ({ ...item })),
      batchStatus,
      batchId,
      processing,
      canConvert: items.some((item) => item.itemStatus === ITEM_STATUS.QUEUED) && !processing,
    };
  }

  function setOption(key, value) {
    if (!(key in options) || options[key] === value) return;
    options = { ...options, [key]: value };
    emit();
  }

  function addFiles(paths) {
    const additions = [];
    for (const raw of paths) {
      if (typeof raw !== "string" || raw.trim().length === 0) continue;
      const path = raw.trim();
      const ext = extensionOf(path);
      additions.push({
        id: nextId(),
        path,
        name: baseName(path),
        ext,
        outputPath: null,
        extractImages: ext === "pdf" && options.extractImages !== "disabled",
        itemStatus: SUPPORTED_EXTENSIONS.includes(ext) ? ITEM_STATUS.QUEUED : ITEM_STATUS.UNSUPPORTED,
        error: null,
      });
    }
    if (additions.length === 0) return;
    items = [...items, ...additions];
    emit();
  }

  function setExtractForItem(path, enabled) {
    let changed = false;
    items = items.map((item) => {
      if (item.path !== path || item.ext !== "pdf" || item.extractImages === enabled) return item;
      changed = true;
      return { ...item, extractImages: enabled };
    });
    if (changed) emit();
  }

  function setExtractForAll(enabled) {
    let changed = false;
    items = items.map((item) => {
      if (item.ext !== "pdf" || item.extractImages === enabled) return item;
      changed = true;
      return { ...item, extractImages: enabled };
    });
    if (changed) emit();
  }

  function clearList() {
    if (processing) return;
    items = [];
    batchId = null;
    batchStatus = "idle";
    emit();
  }

  function outputBaseFor() {
    if (options.outputMode === "custom" && options.outputFolder) {
      return options.outputFolder.replace(/[\\/]+$/, "");
    }
    return null;
  }

  function synthesizeOutputPath(item) {
    if (item.outputPath != null) return item.outputPath;
    const base = outputBaseFor() ?? parentOf(item.path);
    return `${base}/${safeStem(item.path)}.${options.format || "md"}`;
  }

  function batchRequestFor(runnable) {
    return {
      files: runnable.map((item) => item.path),
      outputDirectory: outputBaseFor() ?? parentOf(runnable[0].path),
    };
  }

  async function convertAll() {
    if (processing) return;
    const runnable = items.filter((item) => item.itemStatus === ITEM_STATUS.QUEUED);
    if (runnable.length === 0) return;

    cancelRequested = false;
    processing = true;
    batchStatus = "running";
    batchId = null;
    items = items.map((item) =>
      item.itemStatus === ITEM_STATUS.QUEUED ? { ...item, error: null } : item,
    );
    emit();

    let queue;
    try {
      queue = await adapter.startBatch(batchRequestFor(runnable));
    } catch (error) {
      markAllFailed(runnable, error instanceof Error ? error.message : String(error));
      return;
    }

    if (adapter.isNative) {
      await runNativeBatch(queue, runnable);
    } else {
      await runPreviewBatch(queue, runnable);
    }
  }

  function markAllFailed(runnable, message) {
    const ids = new Set(runnable.map((item) => item.id));
    items = items.map((item) =>
      ids.has(item.id) ? { ...item, itemStatus: ITEM_STATUS.FAILED, error: message } : item,
    );
    finish("failed");
  }

  function finish(status) {
    processing = false;
    batchStatus = status;
    emit();
  }

  async function runPreviewBatch(queue, runnable) {
    batchId = queue?.batchId ?? null;
    const capturedBySource = new Map(
      (queue?.items ?? []).map((item) => [item.sourcePath, item]),
    );

    for (const runItem of runnable) {
      if (batchStatus !== "running" || cancelRequested) break;

      const markProcessing = () => {
        items = items.map((item) =>
          item.id === runItem.id ? { ...item, itemStatus: ITEM_STATUS.PROCESSING } : item,
        );
        emit();
      };
      markProcessing();
      await delayImpl(PREVIEW_PER_ITEM_MS);
      if (batchStatus !== "running" || cancelRequested) break;

      const captured = capturedBySource.get(runItem.path);
      const rejected = captured?.status === "error";
      items = items.map((item) =>
        item.id === runItem.id
          ? {
              ...item,
              itemStatus: rejected ? ITEM_STATUS.FAILED : ITEM_STATUS.COMPLETED,
              outputPath: rejected ? null : (captured?.outputPath ?? synthesizeOutputPath(item)),
              error: rejected ? "The conversion backend rejected this file." : null,
            }
          : item,
      );
      emit();
    }

    if (batchStatus === "running" && !cancelRequested) finish("completed");
  }

  async function runNativeBatch(queue, runnable) {
    batchId = queue?.batchId ?? null;
    const runIds = new Set(runnable.map((item) => item.id));

    for (let attempts = 0; attempts < 400 && batchStatus === "running"; attempts += 1) {
      await delayImpl(pollInterval);
      if (cancelRequested) break;

      let live;
      try {
        live = await adapter.getQueueStatus();
      } catch {
        continue;
      }
      if (!live || !Array.isArray(live.items)) continue;

      const bySource = new Map(live.items.map((item) => [item.sourcePath, item]));
      let changed = false;
      items = items.map((item) => {
        if (!runIds.has(item.id)) return item;
        const liveItem = bySource.get(item.path);
        if (!liveItem) return item;
        if (String(liveItem.status).toLowerCase() === "cancelled") cancelRequested = true;
        const mapped = liveToUi(liveItem.status);
        if (item.itemStatus === mapped && item.outputPath === (liveItem.outputPath ?? item.outputPath)) return item;
        changed = true;
        return {
          ...item,
          itemStatus: mapped,
          outputPath: liveItem.outputPath ?? item.outputPath,
          error: liveItem.error ?? item.error,
        };
      });
      if (changed) emit();

      if (String(live.status).toLowerCase() === "cancelled") break;
    }

    if (!cancelRequested && batchStatus === "running") finish("completed");
  }

  function liveToUi(raw) {
    const value = String(raw ?? "").toLowerCase();
    if (value === "completed" || value === "done") return ITEM_STATUS.COMPLETED;
    if (value === "cancelled") return ITEM_STATUS.CANCELLED;
    if (value === "failed" || value === "error") return ITEM_STATUS.FAILED;
    if (value === "processing" || value === "running") return ITEM_STATUS.PROCESSING;
    if (value === "unsupported") return ITEM_STATUS.UNSUPPORTED;
    return ITEM_STATUS.QUEUED;
  }

  async function cancelPending() {
    if (!processing) return;
    cancelRequested = true;
    try {
      await adapter.cancelBatch();
    } catch {
      // Best-effort native cancellation; the run loops observe the flag too.
    }
    items = items.map((item) =>
      item.itemStatus === ITEM_STATUS.QUEUED || item.itemStatus === ITEM_STATUS.PROCESSING
        ? { ...item, itemStatus: ITEM_STATUS.CANCELLED }
        : item,
    );
    finish("cancelled");
  }

  return {
    subscribe,
    getState,
    setOption,
    addFiles,
    setExtractForItem,
    setExtractForAll,
    clearList,
    convertAll,
    cancelPending,
  };
}