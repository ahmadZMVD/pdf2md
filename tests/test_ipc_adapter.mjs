import assert from "node:assert/strict";
import { invokeCommand, isNativeTauri, mockResponse } from "../src/services/ipc.js";

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
  assert.equal(browserHealth.local_environment.python_available, true);
  assert.equal(logEntries.length, 1);
  assert.equal(logEntries[0][0], "[Mock IPC Call]");

  browserHealth.local_environment.python_available = false;
  const freshBrowserHealth = await invokeCommand("check_system_health");
  assert.equal(freshBrowserHealth.local_environment.python_available, true);

  const futureResponse = await invokeCommand("future_command", { dry_run: true });
  assert.deepEqual(futureResponse, {
    status: "ok",
    mock: true,
    command: "future_command",
    payload: { dry_run: true },
    build_architecture: "browser_mock_tauri_v2",
  });

  let received;
  globalThis.window = {
    __TAURI__: {
      core: {
        invoke: async (...args) => {
          received = args;
          return { status: "ok", source: "native-global" };
        },
      },
    },
  };
  assert.equal(isNativeTauri(), true);
  const nativeResponse = await invokeCommand("check_system_health", { refresh: true });
  assert.deepEqual(nativeResponse, { status: "ok", source: "native-global" });
  assert.deepEqual(received, ["check_system_health", { refresh: true }]);

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
  console.log(
    "IPC adapter tests passed: isolated browser mocks, future payloads, validation, and native delegation",
  );
} finally {
  console.info = originalInfo;
  if (originalWindow === undefined) {
    delete globalThis.window;
  } else {
    globalThis.window = originalWindow;
  }
}
