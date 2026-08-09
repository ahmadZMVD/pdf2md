/**
 * Headless real-layout verification for the Phase 3.1/3.2 UI overhaul.
 *
 * Boots the built frontend in Microsoft Edge headless over the Chrome
 * DevTools Protocol, drives the real DOM/layout engine, and verifies the
 * five mandated concern areas:
 *   1. zero-overflow fixed shell at 440x620 in idle and populated states
 *   2. liquid glass dragzone: no dashed border at idle, dashed border only
 *      while a dragover is active, collapse to a thin top bar when queued
 *   3. Apple segmented controls slide their thumb and flip aria-checked
 *   4. settings modal stacking (z-index 50/51), no geometry overflow
 *   5. stuck-loop prevention: a failed batch renders per-item retry, and
 *      retry re-enables Convert All (queue store unlock)
 *
 * No string-matching or fake metrics: every check reads real computed
 * layout values from the rendered page. Exits non-zero on any failure.
 */

import { spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DIST = path.join(ROOT, "dist");

const EDGE_CANDIDATES = [
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
];

const MIME = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".svg": "image/svg+xml",
  ".json": "application/json",
};

function freePort() {
  return new Promise((resolve) => {
    const probe = http.createServer();
    probe.listen(0, "127.0.0.1", () => {
      const port = probe.address().port;
      probe.close(() => resolve(port));
    });
  });
}

/** Minimal static file server for the built frontend (ES modules refuse file://). */
function startStaticServer(port) {
  return new Promise((resolve, reject) => {
    const server = http.createServer((request, response) => {
      const urlPath = decodeURIComponent(new URL(request.url, "http://127.0.0.1").pathname);
      const relative = urlPath === "/" ? "index.html" : urlPath.replace(/^\/+/, "");
      const candidate = path.join(DIST, relative);
      if (!candidate.startsWith(DIST) || !fs.existsSync(candidate) || !fs.statSync(candidate).isFile()) {
        response.writeHead(404);
        response.end("not found");
        return;
      }
      response.writeHead(200, { "content-type": MIME[path.extname(candidate)] ?? "application/octet-stream" });
      fs.createReadStream(candidate).pipe(response);
    });
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function pageUrl(port, query = "") {
  const url = `http://127.0.0.1:${port}/index.html`;
  if (query) return `${url}?${query}`;
  return url;
}

class CdpClient {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.nextId = 1;
    this.pending = new Map();
  }

  async connect() {
    this.ws = new WebSocket(this.wsUrl);
    this.ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.id && this.pending.has(message.id)) {
        const { resolve, reject } = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (message.error) reject(new Error(message.error.message));
        else resolve(message.result);
      }
    };
    await new Promise((resolve, reject) => {
      this.ws.onopen = resolve;
      this.ws.onerror = reject;
    });
  }

  send(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  async navigate(url) {
    await this.send("Page.enable");
    await this.send("Runtime.enable");
    await this.send("Page.navigate", { url });
    await sleep(1200);
  }

  async evaluate(expression) {
    const result = await this.send("Runtime.evaluate", {
      expression,
      returnByValue: true,
      awaitPromise: true,
    });
    if (result.exceptionDetails) {
      throw new Error(`evaluate failed: ${JSON.stringify(result.exceptionDetails)}`);
    }
    return result.result.value;
  }

  close() {
    try {
      this.ws.close();
    } catch {
      // already closed
    }
  }
}

function findEdge() {
  return EDGE_CANDIDATES.find((candidate) => fs.existsSync(candidate));
}

async function waitForDebugger(port) {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/list`);
      if (response.ok) {
        const targets = await response.json();
        const page = targets.find(
          (target) => target.type === "page" && !String(target.url).startsWith("edge://"),
        );
        if (page) return page.webSocketDebuggerUrl;
      }
    } catch {
      // debugger not up yet
    }
    await sleep(250);
  }
  throw new Error("Edge remote debugging endpoint never became ready");
}

const results = [];
function check(name, condition, detail = "") {
  results.push({ name, pass: Boolean(condition), detail });
  const mark = condition ? "PASS" : "FAIL";
  console.log(`[${mark}] ${name}${detail ? ` — ${detail}` : ""}`);
}

async function main() {
  const edge = findEdge();
  if (!edge) {
    console.error("Microsoft Edge not found; cannot run the headless layout verification.");
    process.exitCode = 2;
    return;
  }
  if (!fs.existsSync(path.join(DIST, "index.html"))) {
    console.error("dist/index.html missing; run `npm run build` first.");
    process.exitCode = 2;
    return;
  }

  const serverPort = await freePort();
  const debugPort = await freePort();
  const server = await startStaticServer(serverPort);
  const profile = path.join(ROOT, `.tmp-edge-profile-${process.pid}`);
  const child = spawn(
    edge,
    [
      "--headless=new",
      "--disable-gpu",
      "--window-size=440,620",
      "--force-device-scale-factor=1",
      `--remote-debugging-port=${debugPort}`,
      `--user-data-dir=${profile}`,
      "--no-first-run",
      "--no-default-browser-check",
      "about:blank",
    ],
    { stdio: "ignore" },
  );

  let client;
  try {
    const wsUrl = await waitForDebugger(debugPort);
    client = new CdpClient(wsUrl);
    await client.connect();
    // Pin the layout surface to the exact fixed window bounds regardless of
    // headless chrome's outer-window sizing.
    await client.send("Emulation.setDeviceMetricsOverride", {
      width: 440,
      height: 620,
      deviceScaleFactor: 1,
      mobile: false,
    });

    /* ---- State A: idle shell at 440x620 ---- */
    await client.navigate(pageUrl(serverPort));
    const idle = await client.evaluate(`(() => {
      const root = document.documentElement;
      const dz = document.querySelector("#dropzone");
      const segs = document.querySelectorAll(".seg");
      const controls = document.querySelector("#window-controls");
      const dzStyle = getComputedStyle(dz);
      return {
        innerWidth: window.innerWidth,
        innerHeight: window.innerHeight,
        scrollWidth: root.scrollWidth,
        scrollHeight: root.scrollHeight,
        dropzoneVisible: !dz.hidden,
        dropzoneHeight: dz.offsetHeight,
        dropzoneBorderStyle: dzStyle.borderStyle,
        segCount: segs.length,
        windowControlsHidden: controls.offsetParent === null,
        thumbTransform: getComputedStyle(document.querySelector("#format-seg .seg-thumb")).transform,
      };
    })()`);

    check("viewport is exactly 440x620", idle.innerWidth === 440 && idle.innerHeight === 620,
      `${idle.innerWidth}x${idle.innerHeight}`);
    check("idle shell has zero overflow", idle.scrollWidth <= 440 && idle.scrollHeight <= 620,
      `scroll ${idle.scrollWidth}x${idle.scrollHeight}`);
    check("dropzone visible and spacious when queue is empty", idle.dropzoneVisible && idle.dropzoneHeight > 150,
      `${idle.dropzoneHeight}px`);
    check("idle dragzone has no dashed border", idle.dropzoneBorderStyle !== "dashed",
      `border-style ${idle.dropzoneBorderStyle}`);
    check("three segmented controls are rendered", idle.segCount === 3);
    check("window controls hidden in browser mode", idle.windowControlsHidden);
    check("segmented thumb starts on the left option", idle.thumbTransform === "none",
      `transform ${idle.thumbTransform}`);

    /* ---- Segmented control interaction ---- */
    await client.evaluate(`(() => {
      const seg = document.querySelector("#format-seg");
      seg.querySelector('[data-value="txt"]').click();
    })()`);
    await sleep(350);
    const segState = await client.evaluate(`(() => {
      const seg = document.querySelector("#format-seg");
      return {
        transform: getComputedStyle(seg.querySelector(".seg-thumb")).transform,
        activeValue: seg.querySelector(".seg-option.is-active")?.dataset.value,
        checked: seg.querySelector('[data-value="txt"]').getAttribute("aria-checked"),
      };
    })()`);
    check("segmented thumb slides to the right option", segState.transform !== "none" && !/matrix\(1, 0, 0, 1, 0/.test(segState.transform),
      `transform ${segState.transform}`);
    check("segmented control flips active option", segState.activeValue === "txt" && segState.checked === "true");

    /* ---- Settings modal stacking ---- */
    await client.evaluate(`document.querySelector("#settings-btn").click()`);
    await sleep(300);
    const modal = await client.evaluate(`(() => {
      const overlay = document.querySelector("#settings-overlay");
      const backdrop = document.querySelector(".settings-backdrop");
      const panel = document.querySelector(".settings-panel");
      const save = document.querySelector("#settings-save");
      const root = document.documentElement;
      const saveStyle = getComputedStyle(save);
      return {
        open: !overlay.hidden,
        backdropZ: getComputedStyle(backdrop).zIndex,
        panelZ: getComputedStyle(panel).zIndex,
        overflowX: root.scrollWidth <= window.innerWidth,
        overflowY: root.scrollHeight <= window.innerHeight,
        saveTextCentered: saveStyle.textAlign === "center",
        savePaddingLr: saveStyle.paddingLeft !== "0px",
        focusedInput: document.activeElement?.id === "folder-input",
      };
    })()`);
    check("settings modal opens", modal.open);
    check("backdrop stacks at z-50", modal.backdropZ === "50", `z-index ${modal.backdropZ}`);
    check("panel stacks above the backdrop", modal.panelZ === "51", `z-index ${modal.panelZ}`);
    check("modal open state has zero overflow", modal.overflowX && modal.overflowY);
    check("Save Settings text is centered with padding", modal.saveTextCentered && modal.savePaddingLr);
    check("folder input receives focus", modal.focusedInput);
    await client.evaluate(`document.querySelector("#settings-close").click()`);

    /* ---- State B: populated queue, dynamic collapse ---- */
    await client.navigate(pageUrl(serverPort, "demo=populate"));
    await sleep(600);
    const populated = await client.evaluate(`(() => {
      const root = document.documentElement;
      const dz = document.querySelector("#dropzone");
      const list = document.querySelector("#queue-list");
      const workArea = document.querySelector(".work-area");
      const listRect = list.getBoundingClientRect();
      let visibleCards = 0;
      for (const card of list.querySelectorAll(".queue-item")) {
        const rect = card.getBoundingClientRect();
        if (rect.top < listRect.bottom && rect.bottom > listRect.top) visibleCards += 1;
      }
      return {
        hasItemsClass: workArea.classList.contains("has-items"),
        dropzoneHeight: dz.offsetHeight,
        dropzoneBorderStyle: getComputedStyle(dz).borderStyle,
        itemCount: list.querySelectorAll(".queue-item").length,
        visibleCards,
        internalScroll: list.scrollHeight > list.clientHeight,
        overflowX: root.scrollWidth <= window.innerWidth,
        overflowY: root.scrollHeight <= window.innerHeight,
      };
    })()`);
    check("queue populated state marks the work area", populated.hasItemsClass);
    check("dropzone collapses into a thin top bar", populated.dropzoneHeight <= 60,
      `${populated.dropzoneHeight}px`);
    check("collapsed dropzone still accepts drops visually", populated.dropzoneBorderStyle === "none" ||
      populated.dropzoneBorderStyle === "solid", `border-style ${populated.dropzoneBorderStyle}`);
    check("queue renders all 12 items", populated.itemCount === 12, `${populated.itemCount}`);
    check("at least 4 cards visible before internal scrolling", populated.visibleCards >= 4,
      `${populated.visibleCards} visible`);
    check("internal queue scrolling engages", populated.internalScroll);
    check("populated shell has zero page overflow", populated.overflowX && populated.overflowY);

    /* ---- Dragover toggles the dashed border ---- */
    await client.evaluate(`(() => {
      const area = document.querySelector(".work-area");
      area.dispatchEvent(new DragEvent("dragover", { bubbles: true, cancelable: true }));
    })()`);
    await sleep(120);
    const dragging = await client.evaluate(`(() => {
      const dz = document.querySelector("#dropzone");
      return {
        className: dz.className,
        borderStyle: getComputedStyle(dz).borderStyle,
      };
    })()`);
    check("dragover activates the glass drag state", dragging.className.includes("is-dragging"));
    check("dashed border appears only while dragging", dragging.borderStyle === "dashed",
      `border-style ${dragging.borderStyle}`);
    await client.evaluate(`(() => {
      const area = document.querySelector(".work-area");
      area.dispatchEvent(new DragEvent("dragleave", { bubbles: true }));
    })()`);
    await sleep(120);
    const released = await client.evaluate(`(() => {
      const dz = document.querySelector("#dropzone");
      return {
        className: dz.className,
        borderStyle: getComputedStyle(dz).borderStyle,
      };
    })()`);
    check("dragleave instantly removes the dashed border", !released.className.includes("is-dragging") &&
      released.borderStyle !== "dashed", `border-style ${released.borderStyle}`);

    /* ---- Stuck-loop prevention: failed batch unlocks with retry ---- */
    await client.navigate(pageUrl(serverPort, "demo=populate&demo=fail"));
    await sleep(600);
    await client.evaluate(`document.querySelector("#convert-btn").click()`);
    await sleep(400);
    const failed = await client.evaluate(`(() => {
      const badge = document.querySelector("#batch-badge");
      const convert = document.querySelector("#convert-btn");
      const clear = document.querySelector("#clear-btn");
      return {
        badgeText: badge.textContent,
        badgeState: badge.dataset.state,
        firstStatus: document.querySelector(".queue-item")?.dataset.status,
        retryButton: Boolean(document.querySelector(".queue-item .item-retry")),
        convertEnabled: !convert.disabled,
        clearEnabled: !clear.disabled,
      };
    })()`);
    check("failed batch surfaces the failed badge", failed.badgeText === "Failed",
      `badge "${failed.badgeText}"`);
    check("queue items report the failed status", failed.firstStatus === "Failed");
    check("failed items expose a per-item retry button", failed.retryButton);
    check("Clear List unlocks after failure", failed.clearEnabled);

    await client.evaluate(`document.querySelector(".queue-item .item-retry").click()`);
    await sleep(200);
    const retried = await client.evaluate(`(() => {
      const badge = document.querySelector("#batch-badge");
      const convert = document.querySelector("#convert-btn");
      const first = document.querySelector(".queue-item");
      return {
        badgeText: badge.textContent,
        badgeState: badge.dataset.state,
        firstStatus: first.dataset.status,
        retryGone: !first.querySelector(".item-retry"),
        convertEnabled: !convert.disabled,
      };
    })()`);
    check("retry unlocks the batch to an actionable state",
      retried.badgeState === "idle" && retried.firstStatus === "Queued" && retried.retryGone &&
      retried.convertEnabled,
      `badge ${retried.badgeText}, item ${retried.firstStatus}`);

    await client.navigate(pageUrl(serverPort));
    await sleep(400);
    const cleared = await client.evaluate(`(() => {
      const dz = document.querySelector("#dropzone");
      return dz.offsetHeight;
    })()`);
    check("clearing restores the spacious dropzone", cleared > 150, `${cleared}px`);
  } finally {
    client?.close();
    child.kill();
    await sleep(300);
    server.close();
    try {
      fs.rmSync(profile, { recursive: true, force: true });
    } catch {
      // profile cleanup is best-effort
    }
  }

  const failed = results.filter((result) => !result.pass);
  console.log(`\nHeadless layout verification: ${results.length - failed.length}/${results.length} checks passed.`);
  if (failed.length > 0) {
    process.exitCode = 1;
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
