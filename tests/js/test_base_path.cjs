const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { create } = require("../../static/base-path.js");

for (const basePath of ["", "/viewer"]) {
  for (const profileToken of [null, "shared-token"]) {
    test(`API, reader links and continuation share one prefix: ${basePath || "root"}/${profileToken || "admin"}`, async () => {
      const prefix = basePath + (profileToken ? `/p/${profileToken}` : "");
      const calls = [];
      const paths = create({ basePath, pathname: prefix + "/reader.html", fetcher: async (url, options) => {
        calls.push({ url, options });
        return { ok: true, json: async () => ({ chapter_id: "saved-chapter", page_index: 4 }) };
      } });
      assert.equal(paths.profileToken, profileToken);
      assert.equal(paths.path("/reader.html?series=s1"), prefix + "/reader.html?series=s1");
      assert.equal(paths.appPath("/style.css"), basePath + "/style.css");
      const { resolve } = require("../../static/reader-position.js");
      assert.deepEqual(await resolve({ seriesId: "s1", fetcher: paths.fetch }), { chapterId: "saved-chapter", pageIndex: 4 });
      assert.equal(calls[0].url, prefix + "/api/series/s1/continue");
      await paths.fetch(prefix + "/api/already-prefixed");
      assert.equal(calls[1].url, prefix + "/api/already-prefixed");
      await paths.fetch("https://external.example/image.jpg");
      assert.equal(calls[2].url, "https://external.example/image.jpg");
    });
  }
}

function embedContext(parentOrigin, allowedOrigins) {
  const html = fs.readFileSync(path.join(__dirname, "../../static/reader.html"), "utf8");
  const code = html.match(/async function initializeEmbed\(\) \{[\s\S]*?(?=\nfunction postReaderEvent)/)[0];
  let options;
  const context = {
    embedRequested: true, params: new URLSearchParams({ parent_origin: parentOrigin }),
    location: { origin: "https://supporter.example" },
    Set,
    fetch: async () => ({ ok: true, json: async () => ({ enabled: allowedOrigins.length > 0, allowed_origins: allowedOrigins }) }),
    WebtoonReaderEmbed: { createBridge: (value) => {
      options = value;
      return require("../../static/embed.js").createBridge(value);
    } },
    window: { parent: {}, addEventListener() {} }, embedBridge: null, leaveReaderForList: () => {},
    document: { body: { classList: { add() {} } }, getElementById: () => ({ setAttribute() {} }) },
    pagesEl: { textContent: "" },
  };
  vm.createContext(context);
  vm.runInContext(code, context);
  return { context, options: () => options };
}

test("same-origin manager embedding works on a future hostname without a cross-origin allowlist", async () => {
  const { context, options } = embedContext("https://supporter.example", []);
  assert.equal(await context.initializeEmbed(), true);
  assert.deepEqual(Array.from(options().allowedOrigins), ["https://supporter.example"]);
});

test("future same-origin framing does not admit an unconfigured cross-origin parent", async () => {
  const { context, options } = embedContext("https://evil.example", ["http://old-lan-host:8230"]);
  assert.equal(await context.initializeEmbed(), false);
  assert.deepEqual(Array.from(options().allowedOrigins), ["https://supporter.example", "http://old-lan-host:8230"]);
  assert.equal(options().allowedOrigins.includes("https://evil.example"), false);
});
