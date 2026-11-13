const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const html = fs.readFileSync(path.join(__dirname, "../../static/reader.html"), "utf8");
const helpers = html.match(/function setProgressSaveError\(visible\) \{[\s\S]*?\n\}/)[0];
const save = html.match(/function saveProgressNow\([\s\S]*?(?=\nfunction scheduleSaveProgress)/)[0];
const close = html.match(/async function leaveReaderForList\([\s\S]*?(?=\ndocument.getElementById\("backLink"\))/)[0];

function reader(fetcher) {
  const messages = [];
  const requests = [];
  const banner = { hidden: true };
  const context = {
    Promise,
    encodeURIComponent,
    clearTimeout,
    currentChapterId: "chapter-7",
    currentPageIndex: 4,
    seriesId: "series-1",
    saveTimer: null,
    embedBridge: { active: true },
    document: { body: { classList: { remove() {} } }, getElementById: () => banner },
    exitBrowserFullscreen: async () => {},
    updateFullscreenButton: () => {},
    postReaderEvent: (type, payload) => messages.push({ type, ...payload }),
    fetch: async (url, options) => { requests.push({ url, options }); return fetcher(url, options); },
  };
  vm.createContext(context);
  vm.runInContext(`${helpers}\n${save}\n${close}`, context);
  return { context, messages, requests, banner };
}

test("failed progress PUT keeps embedded reader open without close acknowledgement", async () => {
  const ctx = reader(async () => ({ ok: false, status: 500 }));
  await ctx.context.leaveReaderForList();
  assert.equal(ctx.banner.hidden, false);
  assert.equal(ctx.messages.some((m) => m.type === "close"), false);
  assert.deepEqual(ctx.messages.map((m) => m.type), ["error"]);
  assert.equal(ctx.messages[0].code, "progress_save_failed");
  assert.equal(ctx.context.currentChapterId, "chapter-7");
  assert.equal(ctx.context.currentPageIndex, 4);
  assert.equal(ctx.requests[0].options.keepalive, true);
});

test("network failure keeps embedded reader open and a retry saves the same position before close", async () => {
  let attempts = 0;
  const ctx = reader(async () => {
    attempts++;
    if (attempts === 1) throw new Error("connection lost");
    return { ok: true, status: 200 };
  });
  await ctx.context.leaveReaderForList();
  assert.equal(ctx.banner.hidden, false);
  assert.equal(ctx.messages.some((m) => m.type === "close"), false);
  await ctx.context.leaveReaderForList();
  assert.equal(ctx.banner.hidden, true);
  assert.deepEqual(ctx.messages.map((m) => m.type), ["error", "progress", "close"]);
  assert.deepEqual(ctx.requests.map((r) => JSON.parse(r.options.body)), [
    { chapter_id: "chapter-7", page_index: 4 },
    { chapter_id: "chapter-7", page_index: 4 },
  ]);
});

test("close acknowledgement waits for the successful progress response", async () => {
  let finish;
  const ctx = reader(() => new Promise((resolve) => { finish = resolve; }));
  const closing = ctx.context.leaveReaderForList();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(ctx.messages.length, 0);
  finish({ ok: true, status: 200 });
  await closing;
  assert.deepEqual(ctx.messages.map((m) => m.type), ["progress", "close"]);
});

test("non-close autosave callers receive false on failure without an unhandled rejection", async () => {
  const ctx = reader(async () => ({ ok: false, status: 500 }));
  assert.equal(await ctx.context.saveProgressNow(), false);
  assert.equal(ctx.messages.some((m) => m.type === "close"), false);
});

test("retry button keeps normal Space activation instead of starting reader autoscroll", () => {
  const handler = html.match(/function handleScrollKeyDown\([\s\S]*?(?=\nfunction handleScrollKeyUp)/)[0];
  let intercepted = false;
  const context = { toggleAutoScroll: () => { intercepted = true; } };
  vm.createContext(context);
  vm.runInContext(handler, context);
  context.handleScrollKeyDown({ target: { tagName: "BUTTON" }, key: " ", code: "Space", preventDefault: () => { intercepted = true; } });
  assert.equal(intercepted, false);
});
