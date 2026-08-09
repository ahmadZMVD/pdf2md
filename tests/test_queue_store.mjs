import assert from "node:assert/strict";
import { ITEM_STATUS, createStore } from "../src/ui/store.js";

const immediate = () => Promise.resolve();

function makeAdapter(overrides = {}) {
  const calls = { starts: [], cancels: 0, statuses: 0 };
  const adapter = {
    isNative: false,
    async startBatch(request) {
      calls.starts.push(request);
      return {
        batchId: 7,
        status: "running",
        items: request.files.map((sourcePath) => {
          const name = String(sourcePath).split(/[\\/]/).at(-1) ?? sourcePath;
          const stem = name.replace(/\.[^.]*$/, "") || "document";
          return { sourcePath, outputPath: `${request.outputDirectory}/${stem}.md`, status: "queued" };
        }),
      };
    },
    async cancelBatch() {
      calls.cancels += 1;
      return { status: "cancelled", items: [] };
    },
    async getQueueStatus() {
      calls.statuses += 1;
      return { status: "running", items: [] };
    },
    ...overrides,
  };
  return { adapter, calls };
}

function namedStore(adapter) {
  return createStore(adapter, { delay: immediate });
}

const samples = [
  "C:/docs/report.pdf",
  "C:/docs/meeting.docx",
  "C:/docs/readme.txt",
  "C:/docs/image.psd",
];

async function main() {
  const { adapter, calls } = makeAdapter();
  const store = namedStore(adapter);

  const initial = store.getState();
  assert.deepEqual(initial.options, {
    format: "md",
    outputMode: "auto",
    extractImages: "auto",
    outputFolder: "",
  });
  assert.equal(initial.batchStatus, "idle");
  assert.equal(initial.processing, false);
  assert.equal(initial.canConvert, false);
  assert.deepEqual(initial.items, []);

  store.addFiles(samples);
  let state = store.getState();
  assert.equal(state.items.length, 4);
  assert.deepEqual(
    state.items.map((item) => item.itemStatus),
    [ITEM_STATUS.QUEUED, ITEM_STATUS.QUEUED, ITEM_STATUS.QUEUED, ITEM_STATUS.UNSUPPORTED],
  );
  assert.deepEqual(
    state.items.map((item) => item.extractImages),
    [true, false, false, false],
    "extract-images defaults true only for PDFs while the option is Auto",
  );
  assert.equal(state.items[3].outputPath, null);
  assert.equal(state.canConvert, true);

  store.setExtractForItem("C:/docs/report.pdf", false);
  state = store.getState();
  assert.equal(state.items[0].extractImages, false);

  store.setExtractForAll(true);
  state = store.getState();
  assert.equal(state.items[0].extractImages, true);
  store.setExtractForItem("C:/docs/report.pdf", false);
  state = store.getState();
  assert.equal(state.items[0].extractImages, false);

  store.setOption("extractImages", "disabled");
  store.addFiles(["C:/docs/scan.pdf"]);
  state = store.getState();
  assert.equal(state.items[4].extractImages, false);
  store.setOption("extractImages", "auto");
  store.addFiles(["C:/docs/scan2.pdf"]);
  state = store.getState();
  assert.equal(state.items[5].extractImages, true);

  store.setOption("format", "txt");
  store.setOption("format", "txt");
  state = store.getState();
  assert.equal(state.options.format, "txt");
  assert.equal(state.items[5].name, "scan2.pdf");

  const mutable = store.getState();
  mutable.items[0].itemStatus = ITEM_STATUS.CANCELLED;
  assert.equal(store.getState().items[0].itemStatus, ITEM_STATUS.QUEUED, "snapshots must be immutable copies");

  await store.convertAll();
  state = store.getState();
  assert.equal(state.batchStatus, "completed");
  assert.equal(state.processing, false);
  assert.equal(state.batchId, 7);
  assert.equal(
    calls.starts.length,
    1,
    "exactly one batch request recorded for the runnable files only",
  );
  assert.deepEqual(calls.starts[0].files, [
    "C:/docs/report.pdf",
    "C:/docs/meeting.docx",
    "C:/docs/readme.txt",
    "C:/docs/scan.pdf",
    "C:/docs/scan2.pdf",
  ]);
  assert.equal(calls.starts[0].outputDirectory, "C:/docs");
  assert.ok(
    state.items.every((item) => item.itemStatus === ITEM_STATUS.COMPLETED || item.itemStatus === ITEM_STATUS.UNSUPPORTED),
  );
  assert.equal(state.items[0].itemStatus, ITEM_STATUS.COMPLETED);
  assert.equal(state.items[0].outputPath, "C:/docs/report.md");
  assert.equal(state.items[3].itemStatus, ITEM_STATUS.UNSUPPORTED, "unsupported files stay untouched by batches");
  assert.equal(state.canConvert, false, "all runnable items completed -> convert disabled");

  store.clearList();
  state = store.getState();
  assert.equal(state.items.length, 0);
  assert.equal(state.batchStatus, "idle");
  assert.equal(state.canConvert, false);

  const adapter2 = makeAdapter();
  const gated = [];
  const gateDelay = (ms) => new Promise((resolve) => gated.push(resolve));
  const slowStore = createStore(adapter2.adapter, { delay: gateDelay });
  slowStore.addFiles(["C:/docs/one.pdf", "C:/docs/two.pdf"]);
  const execution = slowStore.convertAll();
  const midState = slowStore.getState();
  assert.equal(midState.processing, true);
  assert.equal(midState.batchStatus, "running");
  const cancelled = slowStore.cancelPending();
  for (const resolve of gated.splice(0)) resolve();
  await execution;
  await cancelled;
  state = slowStore.getState();
  assert.equal(state.batchStatus, "cancelled");
  assert.equal(adapter2.calls.cancels, 1);
  assert.ok(
    state.items.every((item) => item.itemStatus === ITEM_STATUS.CANCELLED || item.itemStatus === ITEM_STATUS.COMPLETED),
  );

  const failingAdapter = makeAdapter({
    async startBatch() {
      throw new Error("engine offline");
    },
  });
  const failingStore = namedStore(failingAdapter.adapter);
  failingStore.addFiles(["C:/docs/fail.pdf"]);
  await failingStore.convertAll();
  state = failingStore.getState();
  assert.equal(state.batchStatus, "failed");
  assert.equal(state.processing, false);
  assert.equal(state.items[0].itemStatus, ITEM_STATUS.FAILED);
  assert.match(state.items[0].error, /engine offline/);

  const noEvents = makeAdapter();
  const muteStore = namedStore(noEvents.adapter);
  await muteStore.convertAll();
  assert.equal(noEvents.calls.starts.length, 0, "convertAll on an empty queue must not touch the adapter");

  for (const path of ["", "   ", null, 42]) {
    const edgeStore = namedStore(makeAdapter().adapter);
    edgeStore.addFiles([path]);
    assert.equal(edgeStore.getState().items.length, 0);
  }

  const nativeCalls = { starts: [], cancels: 0, statuses: 0 };
  const nativeA = {
    isNative: true,
    async startBatch(request) {
      nativeCalls.starts.push(request);
      return { batchId: 9, status: "running", items: [] };
    },
    async getQueueStatus() {
      nativeCalls.statuses += 1;
      return { status: "completed", items: [] };
    },
    async cancelBatch() {
      nativeCalls.cancels += 1;
      return { status: "cancelled", items: [] };
    },
  };
  const nativeStore = createStore(nativeA, { delay: immediate, pollInterval: 1 });
  nativeStore.addFiles(["Z:/docs/native.pdf"]);
  await nativeStore.convertAll();
  assert.equal(nativeStore.getState().batchStatus, "completed");
  assert.ok(nativeCalls.statuses >= 1, "the native path must poll getQueueStatus");
  assert.equal(nativeCalls.starts.length, 1);

  const subscriber = [];
  const subStore = namedStore(makeAdapter().adapter);
  const unsubscribe = subStore.subscribe((snapshot) => subscriber.push(snapshot.batchStatus));
  subStore.addFiles(["A:/x.pdf"]);
  unsubscribe();
  subStore.clearList();
  assert.ok(subscriber.length >= 1, "subscribers receive store snapshots on mutations");
  assert.equal(subscriber[0], "idle");

  console.log(
    `Queue store tests passed: ${state.items.length} scenarios across creation, toggles, conversion, cancellation, native polling and failures`,
  );
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});