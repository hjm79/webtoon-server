const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { resolve, pageOffset } = require("../../static/reader-position.js");
const html = fs.readFileSync(path.join(__dirname, "../../static/reader.html"), "utf8");
const current = html.match(/function updateCurrentFromVisible\([\s\S]*?(?=\nfunction onPositionChange)/)[0];

function img(page, top, height, loaded = true) {
  return { dataset: { chapter: "chapter-1", page: String(page) }, complete: loaded,
    naturalWidth: loaded ? 720 : 0, naturalHeight: loaded ? 1600 : 0,
    getBoundingClientRect: () => ({ top, bottom: top + height, height }) };
}
function tracker(images) {
  let changes = 0;
  const c = { currentChapterId: "chapter-1", currentPageIndex: 0, currentPageOffset: 0,
    window: { innerHeight: 800 }, pagesEl: { classList: { contains: () => false }, querySelectorAll: () => images },
    onPositionChange: () => { changes++; } };
  vm.createContext(c); vm.runInContext(current, c);
  return { c, changes: () => changes };
}

test("series entry keeps a saved fractional position inside a tall image", async () => {
  const value = await resolve({ seriesId: "one", fetcher: async () => ({ ok: true,
    json: async () => ({ chapter_id: "chapter-1", page_index: 5, page_offset: 0.375 }) }) });
  assert.deepEqual(value, { chapterId: "chapter-1", pageIndex: 5, pageOffset: 0.375 });
});

test("an explicit chapter link may carry its own intra-image position", async () => {
  assert.deepEqual(await resolve({ seriesId: "one", chapterId: "specific", pageIndex: 4, pageOffset: 0.5 }),
    { chapterId: "specific", pageIndex: 4, pageOffset: 0.5 });
  for (const value of [-1, 1.1, NaN, Infinity, "0.4", null]) assert.equal(pageOffset(value), 0);
});

test("scrolling within the same image updates fractional progress", () => {
  let top = -1200;
  const page = img(5, top, 4000);
  page.getBoundingClientRect = () => ({ top, bottom: top + 4000, height: 4000 });
  const f = tracker([page]); f.c.updateCurrentFromVisible();
  assert.equal(f.c.currentPageIndex, 5); assert.equal(f.c.currentPageOffset, 0.3);
  top = -2000; f.c.updateCurrentFromVisible();
  assert.equal(f.c.currentPageOffset, 0.5); assert.equal(f.changes(), 2);
});

test("offscreen reserved earlier pages do not freeze a distant resumed position", () => {
  const f = tracker([img(0, -5000, 1000, false), img(5, -400, 1600)]);
  f.c.updateCurrentFromVisible();
  assert.equal(f.c.currentPageIndex, 5); assert.equal(f.c.currentPageOffset, 0.25);
});

test("a still-visible missing image cannot silently advance to the following image", () => {
  const f = tracker([img(0, -200, 1000, false), img(1, 600, 1000)]);
  f.c.updateCurrentFromVisible();
  assert.equal(f.c.currentPageIndex, 0); assert.equal(f.changes(), 0);
});

function anchoring(ensure) {
  const names = ["restorePendingAnchor", "cancelPendingAnchor"];
  const helpers = names.map((name) => html.match(new RegExp(`function ${name}\\([^]*?\\n\\}`))[0]).join("\n");
  const position = html.match(/async function positionAtImage\([^]*?(?=\nasync function prefetchNextChapter)/)[0];
  const restores = []; let revealed = 0;
  const c = { pendingAnchor: null, anchorTimeout: null, positioningTimer: null,
    clearTimeout() {}, setTimeout: () => 1, beginPositioning() {},
    revealPages: () => { revealed++; }, restoreScrollAnchor: (anchor) => restores.push({ ...anchor }),
    imageLoader: { ensure } };
  vm.createContext(c); vm.runInContext(helpers + "\n" + position, c);
  return { c, restores, revealed: () => revealed };
}

test("late image sizing keeps the saved relative anchor until user input cancels it", async () => {
  const f = anchoring(async () => true); const image = { isConnected: true };
  await f.c.positionAtImage(image, 0.37);
  f.c.restorePendingAnchor();
  assert.equal(f.restores.length, 3);
  assert.ok(f.restores.every((anchor) => anchor.img === image && anchor.fraction === 0.37));
  f.c.cancelPendingAnchor(); f.c.restorePendingAnchor();
  assert.equal(f.restores.length, 3);
});

test("manual input during loading prevents a late image response from moving the reader", async () => {
  let done;
  const f = anchoring(() => new Promise((resolve) => { done = resolve; }));
  const moving = f.c.positionAtImage({ isConnected: true }, 0.62);
  assert.equal(f.restores.length, 1);
  f.c.cancelPendingAnchor(); done(true); await moving;
  assert.equal(f.restores.length, 1);
  assert.equal(f.c.pendingAnchor, null);
});

test("current chapter end navigation targets the last image without loading intervening pages", async () => {
  const source = html.match(/async function moveToChapterBoundary\([^]*?(?=\ndocument.getElementById\("chapterTop"\))/)[0];
  const image = { getBoundingClientRect: () => ({ height: 2000 }) };
  const moves = [];
  const c = { currentChapterId: "chapter-1", currentPageIndex: 0, currentPageOffset: 0,
    window: { innerHeight: 800 }, loadedChapters: [{ id: "chapter-1", pageCount: 80 }],
    pagesEl: { querySelector: (selector) => { assert.match(selector, /data-page="79"/); return image; } },
    CSS: { escape: (v) => v }, stopContinuousScroll() {}, stopAutoScroll() {}, cancelPendingAnchor() {},
    positionAtImage: async (img, fraction) => moves.push({ img, fraction }), updateCurrentFromVisible() {},
    updateReaderPosition() {}, setChromeHidden() {} };
  vm.createContext(c); vm.runInContext(source, c); await c.moveToChapterBoundary(true);
  assert.equal(c.currentPageIndex, 0); assert.equal(moves.length, 1);
  // Progress is assigned only by the visible decoded-image tracker after movement.
  assert.equal(moves[0].img, image); assert.equal(moves[0].fraction, 0.6);
});
