import {
  cancelBatch,
  getQueueStatus,
  isNativeTauri,
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
  formatSelect: document.querySelector("#format-select"),
  destinationSelect: document.querySelector("#destination-select"),
  imagesSelect: document.querySelector("#images-select"),
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
  elements.dropzone.hidden = listVisible;
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

    const badge = document.createElement("span");
    badge.className = "status-badge";
    badge.dataset.status = item.itemStatus;
    badge.innerHTML = `${BADGE_ICONS[item.itemStatus] ?? ""}<span>${item.itemStatus}</span>`;
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
  toastTimer = setTimeout(() => elements.completionToast.classList.remove("is-visible"), 1900);
}

store.subscribe(render);

function openSettings() {
  elements.folderInput.value = store.getState().options.outputFolder ?? "";
  elements.settingsOverlay.hidden = false;
  elements.folderInput.focus();
  elements.folderInput.select();
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

elements.browseFolderBtn.addEventListener("click", () => {
  elements.folderInput.value = "C:/converted";
  elements.folderInput.focus();
});

elements.formatSelect.addEventListener("change", () => {
  store.setOption("format", elements.formatSelect.value);
});

elements.destinationSelect.addEventListener("change", () => {
  store.setOption("outputMode", elements.destinationSelect.value);
});

elements.imagesSelect.addEventListener("change", () => {
  store.setOption("extractImages", elements.imagesSelect.value);
});

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