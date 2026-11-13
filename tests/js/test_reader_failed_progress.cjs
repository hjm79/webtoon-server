const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const html = fs.readFileSync(path.join(__dirname, "../../static/reader.html"), "utf8");
const update = html.match(/function updateCurrentFromVisible\([\s\S]*?(?=\nfunction onPositionChange)/)[0];
const finish = html.match(/function confirmLastChapterAtDocumentEnd\([\s\S]*?(?=\nwindow.addEventListener\("scroll", confirmLastChapterAtDocumentEnd)/)[0];
const blocked = html.match(/function blockedByImageFailure\([^]*?\n\}/)[0];
const save = html.match(/function saveProgressNow\([\s\S]*?(?=\nfunction scheduleSaveProgress)/)[0];
const bannerHelper = html.match(/function setProgressSaveError\(visible\) \{[\s\S]*?\n\}/)[0];
const boundary = html.match(/async function moveToChapterBoundary\([^]*?(?=\ndocument.getElementById\("chapterTop"\))/)[0];

function image(chapter, page, { top = 0, height = 740, failed = false } = {}) {
  return { dataset: { chapter, page: String(page), imageState: failed ? "failed" : "loaded" },
    complete: true, naturalWidth: failed ? 0 : 720, naturalHeight: failed ? 0 : 1600,
    getBoundingClientRect: () => ({ top, bottom: top + height, height }) };
}
function reader(images, page = 0) {
  const requests = []; const events = []; const moves = []; const label = { textContent: "" };
  const banner = { hidden: true, querySelector: () => label };
  const context = {
    seriesId: "series", seriesData: { title: "test", chapters: [{ id: "earlier" }, { id: "last" }] },
    currentChapterId: "last", currentPageIndex: page, currentPageOffset: 0,
    endOfDocumentCheckQueued: false, saveTimer: null,
    requestAnimationFrame: (callback) => callback(), clearTimeout() {},
    window: { scrollY: 0, innerHeight: 800 },
    document: { documentElement: { scrollHeight: 800 }, getElementById: () => banner },
    pagesEl: { querySelectorAll: () => images, classList: { contains: () => false },
      querySelector: () => images.at(-1) },
    loadedChapters: [{ id: "last", pageCount: 4 }],
    chapterById: () => null, chapterTitleEl: { textContent: "" }, highlightSidebar() {},
    updateReaderPosition() {}, updateUrlState() {}, onPositionChange() {},
    CSS: { escape: (value) => value }, encodeURIComponent, Promise,
    embedBridge: { active: true },
    postReaderEvent: (type, body) => events.push({ type, ...body }),
    fetch: async (url, options) => { requests.push({ url, body: JSON.parse(options.body) }); return { ok: true }; },
    stopContinuousScroll() {}, stopAutoScroll() {}, cancelPendingAnchor() {}, setChromeHidden() {},
    positionAtImage: async (img, fraction) => moves.push({ img, fraction }),
  };
  vm.createContext(context);
  vm.runInContext([update, finish, blocked, bannerHelper, save, boundary].join("\n"), context);
  return { context, requests, events, moves, banner, label };
}

test("an offscreen known failure blocks ordinary progress advancement and final-page completion", () => {
  const f = reader([image("last", 1, { top: -2000, failed: true }), image("last", 3)]);
  f.context.updateCurrentFromVisible();
  f.context.confirmLastChapterAtDocumentEnd();
  assert.equal(f.context.currentPageIndex, 0);
  assert.equal(f.requests.length, 0);
});

test("a failed image in an earlier loaded chapter also blocks advancing into the final chapter", () => {
  const f = reader([image("earlier", 10, { top: -2000, failed: true }), image("last", 3)]);
  f.context.updateCurrentFromVisible(); f.context.confirmLastChapterAtDocumentEnd();
  assert.equal(f.context.currentPageIndex, 0);
  assert.equal(f.requests.length, 0);
});

test("chapter end movement cannot preassign progress beyond a known failure", async () => {
  const f = reader([image("last", 1, { top: -2000, failed: true }), image("last", 3)]);
  await f.context.moveToChapterBoundary(true);
  assert.equal(f.moves.length, 1);
  assert.equal(f.context.currentPageIndex, 0);
  assert.equal(f.requests.length, 0);
});

test("a late failure at or before the selected position blocks its PUT and explains the image failure", async () => {
  const f = reader([image("last", 1, { top: -2000, failed: true }), image("last", 3)], 3);
  assert.equal(await f.context.saveProgressNow(), false);
  assert.equal(f.requests.length, 0);
  assert.equal(f.banner.hidden, false);
  assert.match(f.label.textContent, /불러오지 못한 이미지/);
  assert.equal(f.events.at(-1).code, "page_image_failed");
});

test("a later failure does not prevent saving an earlier valid reading position", async () => {
  const f = reader([image("last", 0), image("last", 3, { top: 2000, failed: true })]);
  assert.equal(await f.context.saveProgressNow(), true);
  assert.equal(f.requests.length, 1);
  assert.equal(f.requests[0].body.page_index, 0);
});

test("repairing the failed image restores normal tracking and final-page saving", async () => {
  const failed = image("last", 1, { top: -2000, failed: true });
  const f = reader([failed, image("last", 3)]);
  f.context.updateCurrentFromVisible();
  assert.equal(f.context.currentPageIndex, 0);
  failed.dataset.imageState = "loaded"; failed.naturalWidth = 720; failed.naturalHeight = 1600;
  f.context.updateCurrentFromVisible();
  assert.equal(f.context.currentPageIndex, 3);
  assert.equal(await f.context.saveProgressNow(), true);
  assert.equal(f.requests[0].body.page_index, 3);
});

test("known geometry idle placeholders before a distant resumed image remain allowed", () => {
  const placeholder = image("last", 0, { top: -2000 });
  placeholder.dataset.imageState = "idle"; placeholder.complete = false; placeholder.naturalWidth = 0; placeholder.naturalHeight = 0;
  const f = reader([placeholder, image("last", 3)]);
  f.context.updateCurrentFromVisible();
  assert.equal(f.context.currentPageIndex, 3);
});
