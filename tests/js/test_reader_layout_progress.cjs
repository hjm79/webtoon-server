const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const html = fs.readFileSync(path.join(__dirname, "../../static/reader.html"), "utf8");
const finish = html.match(/function confirmLastChapterAtDocumentEnd\([\s\S]*?(?=\nwindow.addEventListener\("scroll", confirmLastChapterAtDocumentEnd)/)[0];
const update = html.match(/function updateCurrentFromVisible\([\s\S]*?(?=\nfunction onPositionChange)/)[0];

function image(page, { loaded = true, top = 0, bottom = 500, height = bottom - top } = {}) {
  return {
    dataset: { chapter: "only", page: String(page) },
    complete: loaded,
    naturalWidth: loaded ? 600 : 0,
    naturalHeight: loaded ? 1000 : 0,
    getBoundingClientRect: () => ({ top, bottom, height }),
  };
}

function reader(images, { docHeight = 900, scrollY = 0, positioning = false } = {}) {
  let saves = 0;
  let updates = 0;
  const context = {
    endOfDocumentCheckQueued: false,
    requestAnimationFrame: (callback) => callback(),
    seriesData: { title: "실제 함수 검증", chapters: [{ id: "only" }] },
    currentChapterId: "only",
    currentPageIndex: 0,
    chapterTitleEl: { textContent: "" },
    document: { documentElement: { scrollHeight: docHeight } },
    window: { scrollY, innerHeight: 900 },
    pagesEl: { querySelector: () => images[images.length - 1], querySelectorAll: () => images, classList: { contains: () => positioning } },
    CSS: { escape: (value) => value },
    chapterById: () => null,
    highlightSidebar() {},
    updateUrlState() {},
    saveProgressNow: () => { saves++; },
    onPositionChange: () => { updates++; },
    visiblePages: new Map(images.map((img, i) => [i, img])),
  };
  vm.createContext(context);
  vm.runInContext(`${finish}\n${update}`, context);
  return { context, saves: () => saves, updates: () => updates };
}

test("temporary short document cannot mark unloaded last page as chapter completed", () => {
  const ctx = reader([image(0), image(39, { loaded: false, top: 500, bottom: 500, height: 0 })], { docHeight: 500 });
  ctx.context.confirmLastChapterAtDocumentEnd();
  assert.equal(ctx.context.currentPageIndex, 0);
  assert.equal(ctx.saves(), 0);
});

test("last image loading first cannot complete while preceding image layout is missing", () => {
  const ctx = reader([image(0, { loaded: false, height: 0 }), image(39, { top: 400, bottom: 800 })]);
  ctx.context.confirmLastChapterAtDocumentEnd();
  assert.equal(ctx.context.currentPageIndex, 0);
  assert.equal(ctx.saves(), 0);
});

test("last image must actually reach the viewport even when document metrics say bottom", () => {
  const ctx = reader([image(0, { top: 0, bottom: 500 }), image(39, { top: 1400, bottom: 2000 })]);
  ctx.context.confirmLastChapterAtDocumentEnd();
  assert.equal(ctx.saves(), 0);
});

test("decoded visible final page at the real bottom still records completion", () => {
  const ctx = reader([image(0, { top: -500, bottom: 0 }), image(39, { top: 0, bottom: 740 })]);
  ctx.context.confirmLastChapterAtDocumentEnd();
  assert.equal(ctx.context.currentPageIndex, 39);
  assert.equal(ctx.saves(), 1);
});

test("restore-position overlay blocks completion and observer progress until positioned", () => {
  const ctx = reader([image(39, { top: 0, bottom: 740 })], { positioning: true });
  ctx.context.confirmLastChapterAtDocumentEnd();
  ctx.context.updateCurrentFromVisible();
  assert.equal(ctx.context.currentPageIndex, 0);
  assert.equal(ctx.saves(), 0);
  assert.equal(ctx.updates(), 0);
});

test("unloaded or zero-height observer entries cannot replace a real visible reading page", () => {
  const ctx = reader([image(4, { top: 0, bottom: 800 }), image(39, { loaded: false, top: -1, bottom: -1, height: 0 })]);
  ctx.context.updateCurrentFromVisible();
  assert.equal(ctx.context.currentPageIndex, 4);
  assert.equal(ctx.updates(), 1);
});

test("out-of-order last image cannot advance progress past preceding pages that still have no layout", () => {
  const ctx = reader([image(0, { loaded: false, top: 0, bottom: 0, height: 0 }), image(39, { top: 0, bottom: 740 })]);
  ctx.context.updateCurrentFromVisible();
  assert.equal(ctx.context.currentPageIndex, 0);
  assert.equal(ctx.updates(), 0);
});

test("a decoded visible page still updates while only later pages are pending", () => {
  const ctx = reader([image(4, { top: 0, bottom: 740 }), image(39, { loaded: false, top: 740, bottom: 740, height: 0 })]);
  ctx.context.updateCurrentFromVisible();
  assert.equal(ctx.context.currentPageIndex, 4);
  assert.equal(ctx.updates(), 1);
});

test("large decoded pages still count as current with a small visible fraction", () => {
  const ctx = reader([image(7, { top: -2000, bottom: 3000, height: 5000 }), image(8, { top: 3000, bottom: 4000 })]);
  ctx.context.updateCurrentFromVisible();
  assert.equal(ctx.context.currentPageIndex, 7);
  assert.equal(ctx.updates(), 1);
});
