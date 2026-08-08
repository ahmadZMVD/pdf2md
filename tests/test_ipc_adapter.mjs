import assert from "node:assert/strict";
import {
  cancelBatch,
  getQueueStatus,
  invokeCommand,
  isNativeTauri,
  mockResponse,
  startConversionBatch,
} from "../src/services/ipc.js";

const originalWindow = globalThis.window;
const originalInfo = console.info;

try {
  delete globalThis.window;
  const logEntries = [];
  console.info = (...args) => logEntries.push(args);

  assert.equal(isNativeTauri(), false);
  const browserHealth = await invokeCommand("check_system_health");
  assert.equal(browserHealth.status, "ok");
  assert.equal(browserHealth.os, "browser");
  browserHealth.local_environment.python_available = false;
  assert.equal((await invokeCommand("check_system_health")).local_environment.python_available, true);

  const initialQueue = await startConversionBatch({
    files: ["C:/input/report.pdf", "C:/input/report.docx", "C:/input/photo.jpg"],
    outputDirectory: "C:/output",
  });
  assert.deepEqual(
    initialQueue.items.map((item) => item.outputPath),
    ["C:/output/report.md", "C:/output/report_1.md", null],
  );
  assert.equal(initialQueue.status, "running");
  assert.equal(initialQueue.completed, 0);
  assert.equal((await getQueueStatus()).batchId, initialQueue.batchId);

  const cancelledQueue = await cancelBatch();
  assert.equal(cancelledQueue.status, "cancelled");
  assert.equal(cancelledQueue.cancelRequested, true);
  assert.equal(cancelledQueue.completed, 3);
  assert.deepEqual(cancelledQueue.items.map((item) => item.status), ["cancelled", "cancelled", "cancelled"]);
  assert.throws(() => startConversionBatch({ files: [], outputDirectory: "C:/output" }), /at least one file/);
  assert.equal(logEntries.length, 5);
  assert.equal(logEntries[0][0], "[Mock IPC Call]");

  const futureResponse = await invokeCommand("future_command", { dryRun: true });
  assert.deepEqual(futureResponse, {
    status: "ok",
    mock: true,
    command: "future_command",
    payload: { dryRun: true },
    build_architecture: "browser_mock_tauri_v2",
  });

  const calls = [];
  globalThis.window = {
    __TAURI__: {
      core: {
        invoke: async (...args) => {
          calls.push(args);
          return { status: "ok", source: "native-global" };
        },
      },
    },
  };
  assert.equal(isNativeTauri(), true);
  const nativeResponse = await startConversionBatch({
    files: ["C:/input/example.pdf"],
    outputDirectory: "C:/output",
  });
  assert.deepEqual(nativeResponse, { status: "ok", source: "native-global" });
  assert.deepEqual(calls, [["start_conversion_batch", {
    request: { files: ["C:/input/example.pdf"], outputDirectory: "C:/output" },
  }]]);

  globalThis.window = {
    __TAURI_INTERNALS__: {
      invoke: async (...args) => ({ status: "ok", source: "native-internals", args }),
    },
  };
  assert.equal(isNativeTauri(), true);
  const internalsResponse = await invokeCommand("future_command", { native: true });
  assert.deepEqual(internalsResponse, {
    status: "ok",
    source: "native-internals",
    args: ["future_command", { native: true }, undefined],
  });

  assert.deepEqual(mockResponse("future_command", null).payload, null);
  await assert.rejects(() => invokeCommand(""), /non-empty string/);
  await assert.rejects(() => invokeCommand(null), /non-empty string/);
  console.log("IPC adapter tests passed: browser queue contract, cancellation, validation, and native delegation");
} finally {
  console.info = originalInfo;
  if (originalWindow === undefined) {
    delete globalThis.window;
  } else {
    globalThis.window = originalWindow;
  }
}
