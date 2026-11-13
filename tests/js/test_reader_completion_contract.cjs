const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { resolve } = require("../../static/reader-position.js");
const html = fs.readFileSync(path.join(__dirname, "../../static/reader.html"), "utf8");
const tracker = html.match(/function updateCurrentFromVisible\([^]*?(?=\nfunction onPositionChange)/)[0];
const changed = html.match(/function onPositionChange\([^]*?\n\}/)[0];
const blocked = html.match(/function blockedByImageFailure\([^]*?\n\}/)[0];
const save = html.match(/function saveProgressNow\([^]*?(?=\nfunction scheduleSaveProgress)/)[0];
const finish = html.match(/function confirmLastChapterAtDocumentEnd\([^]*?(?=\nwindow.addEventListener\("scroll", confirmLastChapterAtDocumentEnd)/)[0];
const url = html.match(/function updateUrlState\([^]*?\n\}/)[0];
const jump = html.match(/async function jumpToChapter\([^]*?(?=\nfunction openSidebar)/)[0];

function image(page, top, height, extra = {}) {
  return { dataset: { chapter: "last", page: String(page), imageState: "loaded" },
    complete: true, naturalWidth: 720, naturalHeight: height,
    getBoundingClientRect: () => ({ top, bottom: top + height, height }), ...extra };
}
function reader(images, { docHeight = 1000, scrollY = 200 } = {}) {
  const bodies = []; const timers = []; const moves = [];
  const location = { pathname: "/reader", search: "?series=series&chapter=last&page=4&page_offset=0.6&embed=1" };
  const context = { seriesId: "series", seriesData: { title: "Test", chapters: [{ id: "first" }, { id: "last" }] },
    currentChapterId: "last", currentPageIndex: 0, currentPageOffset: 0, saveTimer: null,
    endOfDocumentCheckQueued: false, window: { scrollY, innerHeight: 800 },
    document: { documentElement: { scrollHeight: docHeight }, querySelector: () => images[0] },
    pagesEl: { querySelectorAll: () => images, classList: { contains: () => false } },
    chapterById: () => null, chapterTitleEl: { textContent: "" }, highlightSidebar() {}, updateReaderPosition() {},
    scheduleSaveProgress: () => timers.push(true), setProgressSaveError() {}, postReaderEvent() {},
    clearTimeout() {}, requestAnimationFrame: (callback) => callback(), URLSearchParams, location,
    history: { replaceState(_state, _title, next) { location.search = next.slice(next.indexOf("?")); } },
    fetch: async (_url, options) => { bodies.push(JSON.parse(options.body)); return { ok: true }; },
    loadedChapters: [{ id: "first" }, { id: "last" }], cancelPendingAnchor() {}, closeSidebar() {},
    positionAtImage: async (img, offset) => moves.push({ img, offset }), embedBridge: { active: true },
  };
  vm.createContext(context);
  vm.runInContext([tracker, changed, blocked, save, finish, url, jump].join("\n"), context);
  return { context, bodies, timers, moves, params: () => new URLSearchParams(location.search) };
}

test("a partially read tall final image sends ordinary progress with the precise offset", async () => {
  const f = reader([image(4, -1200, 4000)], { docHeight: 5000, scrollY: 1200 });
  await f.context.saveProgressNow();
  assert.deepEqual(f.bodies, [{ chapter_id: "last", page_index: 4, completed: false, page_offset: 0.3 }]);
  assert.equal(f.params().get("page_offset"), "0.3");
});

test("a short final image stays completed through the following observer and ordinary save", async () => {
  const f = reader([image(0, -200, 500), image(1, 300, 300)]);
  f.context.confirmLastChapterAtDocumentEnd();
  f.context.updateCurrentFromVisible();
  await f.context.saveProgressNow();
  assert.equal(f.context.currentPageIndex, 1);
  assert.equal(f.context.currentPageOffset, 0);
  assert.deepEqual(f.bodies, [
    { chapter_id: "last", page_index: 1, completed: true },
    { chapter_id: "last", page_index: 1, completed: true },
  ]);
  assert.equal(f.params().get("page"), "1");
  assert.equal(f.params().has("page_offset"), false);
});

test("document end retains the correct offset inside a tall final image", async () => {
  const f = reader([image(4, -3200, 4000)]);
  await f.context.saveProgressNow();
  assert.deepEqual(f.bodies, [{ chapter_id: "last", page_index: 4, completed: true, page_offset: 0.8 }]);
});

test("a visible pending page prevents final completion even with reserved geometry", async () => {
  const pending = image(0, -200, 500, { complete: false, naturalWidth: 0, naturalHeight: 0 });
  const f = reader([pending, image(1, 300, 300)]);
  f.context.confirmLastChapterAtDocumentEnd();
  assert.equal(f.bodies.length, 0);
  assert.equal(f.context.currentPageIndex, 0);
  await f.context.saveProgressNow();
  assert.equal(f.bodies[0].completed, false);
});

test("chapter navigation clears a stale fractional URL before an explicit-link reload", async () => {
  const f = reader([image(0, 0, 1000)]);
  await f.context.jumpToChapter({ id: "first", label: "1" });
  const params = f.params();
  assert.equal(params.get("chapter"), "first");
  assert.equal(params.get("page"), "0");
  assert.equal(params.has("page_offset"), false);
  assert.equal(params.get("embed"), "1");
  assert.equal(f.moves[0].offset, 0);
  assert.deepEqual(await resolve({ seriesId: "series", chapterId: params.get("chapter"),
    pageIndex: Number(params.get("page")), pageOffset: Number(params.get("page_offset")) }),
  { chapterId: "first", pageIndex: 0 });
});

test("scrolling to another page synchronizes its own offset and preserves precise deep links", async () => {
  const f = reader([image(7, -960, 1600)], { docHeight: 5000, scrollY: 1200 });
  f.context.updateCurrentFromVisible();
  const params = f.params();
  assert.equal(params.get("page"), "7");
  assert.equal(params.get("page_offset"), "0.6");
  assert.deepEqual(await resolve({ seriesId: "series", chapterId: params.get("chapter"),
    pageIndex: Number(params.get("page")), pageOffset: Number(params.get("page_offset")) }),
  { chapterId: "last", pageIndex: 7, pageOffset: 0.6 });
  f.context.updateUrlState("last", 0);
  assert.equal(f.params().has("page_offset"), false);
});
