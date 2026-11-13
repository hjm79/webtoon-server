const assert = require("node:assert/strict");
const test = require("node:test");
const { resolve } = require("../../static/reader-position.js");

test("chapter-specific links keep the exact chapter and page without querying progress", async () => {
  const position = await resolve({ seriesId: "series-1", chapterId: "chapter-9", pageIndex: 4, fetcher: () => {
    throw new Error("explicit chapter must not be replaced");
  } });
  assert.deepEqual(position, { chapterId: "chapter-9", pageIndex: 4 });
});

test("series-only entry uses the first chapter returned for an unread series", async () => {
  const paths = [];
  const position = await resolve({ seriesId: "series-1", chapterId: null, pageIndex: 99, fetcher: async (path) => {
    paths.push(path);
    return { ok: true, json: async () => ({ chapter_id: "chapter-1", page_index: 0 }) };
  } });
  assert.deepEqual(paths, ["/api/series/series-1/continue"]);
  assert.deepEqual(position, { chapterId: "chapter-1", pageIndex: 0 });
});

test("series-only entry resumes the browser profile's saved chapter and page", async () => {
  const position = await resolve({ seriesId: "series/one", fetcher: async (path) => {
    assert.equal(path, "/api/series/series%2Fone/continue");
    return { ok: true, json: async () => ({ chapter_id: "chapter-6", page_index: 17 }) };
  } });
  assert.deepEqual(position, { chapterId: "chapter-6", pageIndex: 17 });
});

test("authorization failure cannot silently open the latest or first chapter", async () => {
  await assert.rejects(resolve({ seriesId: "series-1", fetcher: async () => ({ ok: false, status: 401 }) }), /unavailable/);
});

test("missing series and malformed continuation do not produce an arbitrary chapter", async () => {
  await assert.rejects(resolve({ seriesId: null }), /series is required/);
  await assert.rejects(resolve({ seriesId: "series-1", fetcher: async () => ({ ok: true, json: async () => ({ page_index: 0 }) }) }), /no chapter/);
});
