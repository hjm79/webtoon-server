const assert = require("node:assert/strict");
const test = require("node:test");
const { createBridge } = require("../../static/embed.js");

function frame({ standalone = false } = {}) {
  const messages = [];
  const listeners = new Map();
  const parent = { postMessage: (data, origin) => messages.push({ data, origin }) };
  const win = {
    parent,
    addEventListener: (name, listener) => listeners.set(name, listener),
    removeEventListener: (name, listener) => {
      if (listeners.get(name) === listener) listeners.delete(name);
    },
  };
  if (standalone) win.parent = win;
  return { win, parent, messages, listeners };
}

test("standalone reader never creates a parent channel", () => {
  const ctx = frame({ standalone: true });
  const bridge = createBridge({ window: ctx.win, parentOrigin: "http://manager.test", allowedOrigins: ["http://manager.test"] });
  bridge.post("ready");
  assert.equal(bridge.active, false);
  assert.equal(ctx.listeners.size, 0);
  assert.equal(ctx.messages.length, 0);
});

for (const parentOrigin of ["*", "http://manager.test.evil", "http://manager.test/path", "http://manager.test/", "null", "javascript:alert(1)"]) {
  test(`untrusted parent origin cannot activate bridge: ${parentOrigin}`, () => {
    const ctx = frame();
    const bridge = createBridge({ window: ctx.win, parentOrigin, allowedOrigins: ["http://manager.test"] });
    bridge.post("ready");
    assert.equal(bridge.active, false);
    assert.equal(ctx.messages.length, 0);
  });
}

test("messages target the exact allowlisted origin and cannot override protocol fields", () => {
  const ctx = frame();
  const bridge = createBridge({ window: ctx.win, parentOrigin: "http://manager.test", allowedOrigins: ["http://manager.test"] });
  bridge.post("progress", { series_id: "series-1", chapter_id: "chapter-2", page_index: 3, source: "evil", version: 99, type: "evil" });
  assert.equal(bridge.active, true);
  assert.deepEqual(ctx.messages, [{
    origin: "http://manager.test",
    data: { series_id: "series-1", chapter_id: "chapter-2", page_index: 3, source: "webtoon-reader", version: 1, type: "progress" },
  }]);
});

test("close handshake ignores wrong origins, unrelated windows and protocol versions", async () => {
  const ctx = frame();
  let closed = 0;
  createBridge({ window: ctx.win, parentOrigin: "http://manager.test", allowedOrigins: ["http://manager.test"], onClose: async () => { closed++; } });
  const receive = ctx.listeners.get("message");
  const data = { source: "webtoon-manager", version: 1, type: "close" };
  await receive({ source: ctx.parent, origin: "http://evil.test", data });
  await receive({ source: {}, origin: "http://manager.test", data });
  await receive({ source: ctx.parent, origin: "http://manager.test", data: { ...data, version: 2 } });
  await receive({ source: ctx.parent, origin: "http://manager.test", data: { ...data, source: "other-app" } });
  assert.equal(closed, 0);
  await receive({ source: ctx.parent, origin: "http://manager.test", data });
  assert.equal(closed, 1);
});

test("concurrent parent close requests do not race progress saves", async () => {
  const ctx = frame();
  let complete;
  let saves = 0;
  const bridge = createBridge({ window: ctx.win, parentOrigin: "http://manager.test", allowedOrigins: ["http://manager.test"], onClose: () => {
    saves++;
    return new Promise((resolve) => { complete = resolve; });
  } });
  const event = { source: ctx.parent, origin: "http://manager.test", data: { source: "webtoon-manager", version: 1, type: "close" } };
  const first = ctx.listeners.get("message")(event);
  await ctx.listeners.get("message")(event);
  assert.equal(saves, 1);
  complete();
  await first;
  bridge.destroy();
  assert.equal(ctx.listeners.size, 0);
});
