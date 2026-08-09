import {
  cancelBatch,
  getQueueStatus,
  isNativeTauri,
  selectOutputFolder,
  startConversionBatch,
} from "./services/ipc.js";
import { ITEM_STATUS, createStore } from "./ui/store.js";

const adapter = {
  startBatch: startConversionBatch,
  cancelBatch,
  getQueueStatus,
  isNative: isNativeTauri(),
};

const store = createStore(adapter);

const elements = {
  batchBadge: document.querySelector("#batch-badge"),
  formatSeg: document.querySelector("#format-seg"),
  destinationSeg: document.querySelector("#destination-seg"),
  imagesSeg: document.querySelector("#images-seg"),
  settingsBtn: document.querySelector("#settings-btn"),
  settingsOverlay: document.querySelector("#settings-overlay"),
  settingsClose: document.querySelector("#settings-close"),
  settingsSave: document.querySelector("#settings-save"),
  backdrop: document.querySelector(".settings-backdrop"),
  folderInput: document.querySelector("#folder-input"),
  browseFolderBtn: document.querySelector("#browse-folder-btn"),
  fileInput: document.querySelector("#file-input"),
  dropzone: document.querySelector("#dropzone"),
  browseBtn: document.querySelector("#browse-btn"),
  workArea: document.querySelector(".work-area"),
  queuePanel: document.querySelector("#queue-panel"),
  queueList: document.querySelector("#queue-list"),
  queueCount: document.querySelector("#queue-count"),
  applyAll: document.querySelector("#apply-all-input"),
  clearBtn: document.querySelector("#clear-btn"),
  convertBtn: document.querySelector("#convert-btn"),
  completionToast: document.querySelector("#completion-toast"),
  completionText: document.querySelector("#completion-text"),
  winMinimize: document.querySelector("#win-minimize"),
  winMaximize: document.querySelector("#win-maximize"),
  winClose: document.querySelector("#win-close"),
  windowControls: document.querySelector("#window-controls"),
  titlebar: document.querySelector(".titlebar"),
};

let toastTimer = null;
let lastBatchStatus = "idle";

const FILE_GLYPHS = {
  pdf: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/><path d="M8 13h.01M12 13h.01M16 13h.01M8 17h.01M12 17h.01"/></svg>',
  docx: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/><path d="M12 11 8.5 18M12 11l3.5 7M8.9 15.8h6.2"/></svg>',
  txt: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/><path d="M8.5 12h7M8.5 15.5h7"/></svg>',
  unknown: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4 3h16v18H4z"/><path d="M8 9h8M8 13h8M8 17h5"/></svg>',
};

const BADGE_ICONS = {
  [ITEM_STATUS.QUEUED]: "",
  [ITEM_STATUS.PROCESSING]: '<span class="badge-icon" aria-hidden="true"></span>',
  [ITEM_STATUS.COMPLETED]: "✓",
  [ITEM_STATUS.FAILED]: "✕",
  [ITEM_STATUS.UNSUPPORTED]: "⚠",
  [ITEM_STATUS.CANCELLED]: "—",
};

const BADGE_LABELS = {
  [ITEM_STATUS.QUEUED]: "Queued",
  [ITEM_STATUS.PROCESSING]: "Converting",
  [ITEM_STATUS.COMPLETED]: "Done",
  [ITEM_STATUS.FAILED]: "Failed",
  [ITEM_STATUS.UNSUPPORTED]: "Unsupported",
  [ITEM_STATUS.CANCELLED]: "Skip",
};

function fileGlyphPath(ext) {
  return FILE_GLYPHS[ext] ?? FILE_GLYPHS.unknown;
}

function rowGlyphClass(ext) {
  if (ext === "pdf") return "is-pdf";
  if (ext === "docx") return "is-docx";
  if (ext === "txt") return "is-txt";
  return "is-unsupported";
}

function renderQueue(state) {
  const listVisible = state.items.length > 0;
  elements.workArea.classList.toggle("has-items", listVisible);
  elements.queuePanel.hidden = !listVisible;

  if (!listVisible) return;

  elements.queueCount.textContent = `${state.items.length} file${state.items.length === 1 ? "" : "s"}`;

  const pdfCount = state.items.filter((item) => item.ext === "pdf" && item.itemStatus === ITEM_STATUS.QUEUED).length;
  const enabledCount = state.items.filter(
    (item) => item.ext === "pdf" && item.extractImages && item.itemStatus === ITEM_STATUS.QUEUED,
  ).length;
  elements.applyAll.checked = pdfCount > 0 && enabledCount === pdfCount;
  elements.applyAll.disabled = state.processing || pdfCount === 0;

  const rows = state.items.map((item) => {
    const row = document.createElement("li");
    row.className = `queue-item${item.itemStatus === ITEM_STATUS.CANCELLED ? " is-cancelled" : ""}`;
    row.dataset.status = item.itemStatus;

    const glyph = document.createElement("span");
    glyph.className = `file-glyph ${rowGlyphClass(item.ext)}`;
    glyph.innerHTML = fileGlyphPath(item.ext);

    const main = document.createElement("div");
    main.className = "item-main";
    const name = document.createElement("p");
    name.className = "item-name";
    name.textContent = item.name;
    name.title = item.path;
    const path = document.createElement("p");
    path.className = "item-path";
    path.textContent = item.outputPath ?? abbreviatePath(item);
    path.title = item.error ?? "";
    main.append(name, path);

    row.append(glyph, main);

    if (item.ext === "pdf" && !state.processing) {
      const toggle = document.createElement("label");
      toggle.className = "extract-toggle";
      toggle.title = "Extract images from this PDF";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = item.extractImages;
      input.addEventListener("change", () => store.setExtractForItem(item.path, input.checked));
      const label = document.createElement("span");
      label.textContent = "IMG";
      toggle.append(input, label);
      row.append(toggle);
    }

    if (item.itemStatus === ITEM_STATUS.FAILED && !state.processing) {
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "item-retry";
      retry.textContent = "↻ Retry";
      retry.title = "Reset this item to Queued and run the batch again";
      retry.addEventListener("click", () => store.retryItem(item.path));
      row.append(retry);
    }

    const badge = document.createElement("span");
    badge.className = "status-badge";
    badge.dataset.status = item.itemStatus;
    badge.innerHTML = `${BADGE_ICONS[item.itemStatus] ?? ""}<span>${BADGE_LABELS[item.itemStatus] ?? item.itemStatus}</span>`;
    row.append(badge);

    return row;
  });

  elements.queueList.replaceChildren(...rows);
}

function abbreviatePath(item) {
  const name = item.name.replace(/\.[^.]*$/, "");
  const ext = item.ext || "md";
  const folder = item.path.split(/[\\/]/).slice(0, -1).join("/");
  return `${folder}/${name}.${ext}`;
}

function renderBatchBadge(state) {
  const map = {
    idle: "Ready",
    running: "Converting…",
    completed: "Done",
    failed: "Failed",
    cancelled: "Cancelled",
  };
  elements.batchBadge.textContent = map[state.batchStatus] ?? "Ready";
  elements.batchBadge.dataset.state = state.batchStatus;
}

function renderActions(state) {
  elements.clearBtn.disabled = state.processing || state.items.length === 0;
  elements.convertBtn.disabled = !state.canConvert;

  if (state.processing) {
    elements.convertBtn.textContent = "Cancel Batch";
    elements.convertBtn.classList.add("is-cancelling");
  } else {
    elements.convertBtn.textContent = "Convert All";
    elements.convertBtn.classList.remove("is-cancelling");
  }
}

function render(state) {
  renderQueue(state);
  renderBatchBadge(state);
  renderActions(state);

  if (state.batchStatus === "completed" && lastBatchStatus !== "completed") {
    showCompletionToast("Batch complete");
  } else if (state.batchStatus === "failed" && lastBatchStatus !== "failed") {
    showCompletionToast("Some files failed", true);
  } else if (state.batchStatus === "cancelled" && lastBatchStatus !== "cancelled") {
    showCompletionToast("Batch cancelled", true);
  }
  lastBatchStatus = state.batchStatus;
}

function showCompletionToast(message, isError = false) {
  clearTimeout(toastTimer);
  elements.completionText.textContent = message;
  elements.completionToast.classList.add("is-visible");
  if (isError) elements.completionToast.classList.add("is-error");
  else elements.completionToast.classList.remove("is-error");
  toastTimer = setTimeout(() => {
    elements.completionToast.classList.remove("is-visible");
    elements.completionToast.classList.remove("is-error");
  }, 1900);
}

store.subscribe(render);

/* ===== Segmented controls ===== */

function syncSeg(seg, value) {
  const options = Array.from(seg.querySelectorAll(".seg-option"));
  options.forEach((option) => {
    const active = option.dataset.value === value;
    option.classList.toggle("is-active", active);
    option.setAttribute("aria-checked", String(active));
  });
  seg.dataset.active = String(options.findIndex((option) => option.dataset.value === value));
}

function bindSeg(seg, optionKey) {
  const options = seg.querySelectorAll(".seg-option");
  for (const option of options) {
    option.addEventListener("click", () => {
      store.setOption(optionKey, option.dataset.value);
    });
  }
}

store.subscribe((state) => {
  syncSeg(elements.formatSeg, state.options.format);
  syncSeg(elements.destinationSeg, state.options.outputMode);
  syncSeg(elements.imagesSeg, state.options.extractImages);
});

bindSeg(elements.formatSeg, "format");
bindSeg(elements.destinationSeg, "outputMode");
bindSeg(elements.imagesSeg, "extractImages");

/* ===== Settings modal ===== */

function openSettings() {
  elements.folderInput.value = store.getState().options.outputFolder ?? "";
  elements.settingsOverlay.hidden = false;
  requestAnimationFrame(() => {
    elements.folderInput.focus();
    elements.folderInput.select();
  });
}

function closeSettings() {
  elements.settingsOverlay.hidden = true;
  elements.settingsBtn.focus();
}

elements.settingsBtn.addEventListener("click", openSettings);
elements.settingsClose.addEventListener("click", closeSettings);
elements.backdrop?.addEventListener("click", closeSettings);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !elements.settingsOverlay.hidden) closeSettings();
});

elements.settingsSave.addEventListener("click", () => {
  store.setOption("outputFolder", elements.folderInput.value.trim());
  closeSettings();
});

elements.browseFolderBtn.addEventListener("click", async () => {
  try {
    const picked = await selectOutputFolder();
    if (typeof picked === "string" && picked.length > 0) {
      elements.folderInput.value = picked;
    }
  } catch {
    // A cancelled or failed native dialog keeps the previous value untouched.
  }
  elements.folderInput.focus();
});

/* ===== File browsing & drag & drop ===== */

elements.browseBtn.addEventListener("click", (event) => {
  event.preventDefault();
  elements.fileInput.click();
});

elements.dropzone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    elements.fileInput.click();
  }
});

elements.fileInput.addEventListener("change", () => {
  const files = Array.from(elements.fileInput.files ?? []).map((file) => file.name);
  if (files.length > 0) store.addFiles(files);
  elements.fileInput.value = "";
});

elements.workArea.addEventListener("dragover", (event) => {
  event.preventDefault();
  elements.dropzone.classList.add("is-dragging");
});

elements.workArea.addEventListener("dragleave", (event) => {
  if (event.target === elements.workArea || event.relatedTarget === null) {
    elements.dropzone.classList.remove("is-dragging");
  }
});

elements.workArea.addEventListener("drop", (event) => {
  event.preventDefault();
  elements.dropzone.classList.remove("is-dragging");
  const files = Array.from(event.dataTransfer?.files ?? []).map((file) => file.name);
  if (files.length > 0) store.addFiles(files);
});

elements.applyAll.addEventListener("change", () => {
  store.setExtractForAll(elements.applyAll.checked);
});

elements.clearBtn.addEventListener("click", () => store.clearList());
elements.convertBtn.addEventListener("click", () => {
  if (store.getState().processing) {
    store.cancelPending();
  } else {
    store.convertAll();
  }
});

/* ===== Frameless window controls (native only) ===== */

async function bindWindowControls() {
  if (!adapter.isNative) {
    elements.windowControls.hidden = true;
    return;
  }
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  const current = getCurrentWindow();

  elements.winMinimize.addEventListener("click", () => {
    current.minimize();
  });

  elements.winMaximize.addEventListener("click", async () => {
    await current.toggleMaximize();
    const maximized = await current.isMaximized();
    elements.winMaximize.classList.toggle("is-maximized", maximized);
  });

  elements.winClose.addEventListener("click", () => {
    current.close();
  });

  const maximized = await current.isMaximized();
  elements.winMaximize.classList.toggle("is-maximized", maximized);
}

bindWindowControls();

/* ===== Geometry probe ===== */

function probeGeometry() {
  const root = document.documentElement;
  const ok = root.scrollWidth <= window.innerWidth && root.scrollHeight <= window.innerHeight;
  root.dataset.geometryOk = ok ? "true" : "false";
}

function scheduleProbe() {
  requestAnimationFrame(() => requestAnimationFrame(probeGeometry));
}

const observer = new MutationObserver(scheduleProbe);
observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["class"] });

window.addEventListener("resize", probeGeometry);
store.subscribe(scheduleProbe);

function populateDemoQueue() {
  const params = new URLSearchParams(window.location.search);
  if (params.get("demo") !== "populate" || isNativeTauri()) return;
  const base = "C:/samples/";
  store.addFiles([
    `${base}report-2026.pdf`,
    `${base}meeting-notes.docx`,
    `${base}readme.txt`,
    `${base}unsupported.psd`,
    ...Array.from({ length: 8 }, (_, index) => `${base}chapter-0${index + 1}.pdf`),
  ]);
}

scheduleProbe();
populateDemoQueue();

if (!adapter.isNative) {
  // QA seam: lets the headless layout verifier drive the real store in the
  // browser mock runtime. Never exposed in the packaged native shell.
  window.__pdf2mdStore = store;
}
