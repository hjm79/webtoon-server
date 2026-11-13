const assert = require("node:assert/strict");
const test = require("node:test");
const { createLoader, validSize } = require("../../static/reader-images.js");

function fixture(options = {}) {
  let observerCallback;
  const observed = [];
  const timers = [];
  const loaded = [];
  const failed = [];
  let disconnected = false;
  const loader = createLoader({
    observerFactory(callback, config) {
      observerCallback = callback;
      assert.equal(config.rootMargin, "1200px 0px");
      return { observe: (img) => observed.push(img), disconnect() { disconnected = true; } };
    },
    schedule(callback) { timers.push(callback); return timers.length; },
    cancel(id) { timers[id - 1] = null; },
    onLoaded: (img) => loaded.push(img),
    onFailed: (img, retry) => failed.push({ img, retry }),
    ...options,
  });
  function image(number) {
    const requests = [];
    const img = {
      dataset: {}, style: {}, isConnected: true, naturalWidth: 0, naturalHeight: 0,
      requests, removed: [],
      set src(value) { requests.push(value); },
      removeAttribute(name) { this.removed.push(name); },
      succeed(width = 720, height = 1600) { this.naturalWidth = width; this.naturalHeight = height; this.onload?.(); },
      fail() { this.onerror?.(); },
    };
    loader.register(img, `/viewer/api/chapters/ch/pages/${number}`, { width: 720, height: 1600 });
    return img;
  }
  return { loader, image, observed, loaded, failed, timers,
    visible: (...imgs) => observerCallback(imgs.map((target) => ({ target, isIntersecting: true }))),
    hidden: (...imgs) => observerCallback(imgs.map((target) => ({ target, isIntersecting: false }))),
    tick() { const callback = timers.shift(); callback?.(); },
    disconnected: () => disconnected,
  };
}

test("page dimensions reserve geometry without making an image request", () => {
  const f = fixture(); const img = f.image(0);
  assert.equal(img.width, 720); assert.equal(img.height, 1600);
  assert.equal(img.style.aspectRatio, "720 / 1600");
  assert.equal(img.dataset.dimensionsKnown, "true");
  assert.equal(img.requests.length, 0);
  assert.deepEqual(f.observed, [img]);
});

test("only viewport-near images are queued and at most three run concurrently", async () => {
  const f = fixture(); const imgs = Array.from({ length: 6 }, (_, i) => f.image(i));
  f.visible(...imgs.slice(0, 5));
  assert.deepEqual(imgs.map((img) => img.requests.length), [1, 1, 1, 0, 0, 0]);
  imgs[1].succeed();
  assert.deepEqual(imgs.map((img) => img.requests.length), [1, 1, 1, 1, 0, 0]);
  assert.equal(await f.loader.ensure(imgs[1]), true);
});

test("the restore target takes precedence over queued neighboring pages", () => {
  const f = fixture(); const imgs = Array.from({ length: 6 }, (_, i) => f.image(i));
  f.visible(...imgs.slice(0, 5));
  f.loader.ensure(imgs[5], { priority: true });
  imgs[0].succeed();
  assert.equal(imgs[5].requests.length, 1);
  assert.equal(imgs[3].requests.length, 0);
});

test("newly visible pages bypass observer-only requests that have left the viewport", () => {
  const f = fixture(); const imgs = Array.from({ length: 9 }, (_, i) => f.image(i));
  f.visible(...imgs.slice(0, 8));
  f.hidden(...imgs.slice(0, 8));
  f.visible(imgs[8]);
  assert.ok(imgs.slice(3, 8).every((img) => img.dataset.imageState === "idle"));
  assert.ok(imgs.slice(0, 3).every((img) => img.dataset.imageState === "loading"));
  assert.ok(imgs.slice(0, 3).every((img) => img.removed.length === 0));
  imgs[0].succeed();
  assert.equal(imgs[8].requests.length, 1);
  assert.ok(imgs.slice(3, 8).every((img) => img.requests.length === 0));
  f.visible(imgs[4]);
  imgs[1].succeed();
  assert.equal(imgs[4].requests.length, 1);
});

test("explicitly ensured queued pages stay pinned after observer demand leaves", async () => {
  const f = fixture({ concurrency: 1 }); const a = f.image(0); const target = f.image(1);
  f.visible(a, target);
  const pending = f.loader.ensure(target, { priority: true });
  f.hidden(a, target);
  a.succeed();
  assert.equal(target.requests.length, 1);
  target.succeed();
  assert.equal(await pending, true);
});

test("an observer-only retry waits offscreen and resumes with the existing retry budget", () => {
  const f = fixture(); const img = f.image(0);
  f.visible(img); img.fail(); f.hidden(img); f.tick();
  assert.equal(img.requests.length, 1);
  assert.equal(img.dataset.imageState, "idle");
  f.visible(img);
  assert.equal(img.requests.length, 2);
  assert.match(img.requests[1], /retry=1$/);
  img.fail(); f.tick(); img.fail();
  assert.equal(img.requests.length, 3);
  assert.equal(img.dataset.imageState, "failed");
});

test("an explicit ensure during an offscreen retry retains a settling promise", async () => {
  const f = fixture(); const img = f.image(0);
  f.visible(img); img.fail(); f.hidden(img);
  const pending = f.loader.ensure(img);
  f.tick();
  assert.equal(img.requests.length, 2);
  img.succeed();
  assert.equal(await pending, true);
});

test("destroy settles pinned queued and retry-waiting requests", async () => {
  const f = fixture({ concurrency: 1 }); const a = f.image(0); const b = f.image(1); const c = f.image(2);
  const first = f.loader.ensure(a); a.fail();
  const second = f.loader.ensure(b); const third = f.loader.ensure(c);
  f.hidden(a, b, c); f.loader.destroy();
  assert.deepEqual(await Promise.all([first, second, third]), [false, false, false]);
  f.tick();
  assert.equal(a.requests.length, 1);
  assert.equal(c.requests.length, 0);
});

test("duplicate visibility notifications share the same image load", async () => {
  const f = fixture(); const img = f.image(0);
  const first = f.loader.ensure(img);
  assert.equal(first, f.loader.ensure(img));
  f.visible(img, img);
  assert.equal(img.requests.length, 1);
  img.succeed();
  assert.equal(await first, true);
  assert.deepEqual(f.loaded, [img]);
});

test("automatic recovery is bounded to the initial request plus two retries", async () => {
  const f = fixture(); const img = f.image(0); const result = f.loader.ensure(img);
  img.fail(); f.tick();
  img.fail(); f.tick();
  img.fail();
  assert.equal(await result, false);
  assert.equal(img.requests.length, 3);
  assert.equal(f.timers.length, 0);
  assert.equal(img.dataset.imageState, "failed");
  assert.equal(f.failed.length, 1);
  assert.match(img.requests[1], /retry=1$/);
  assert.match(img.requests[2], /retry=2$/);
  f.visible(img);
  assert.equal(img.requests.length, 3);
});

test("manual retry can recover a failed page without reloading other pages", async () => {
  const f = fixture({ maxRetries: 0 }); const img = f.image(0); const other = f.image(1);
  const first = f.loader.ensure(img); img.fail(); await first;
  const retry = f.failed[0].retry();
  assert.equal(img.requests.length, 2);
  assert.equal(other.requests.length, 0);
  img.succeed();
  assert.equal(await retry, true);
  assert.equal(img.dataset.imageState, "loaded");
});

test("a retry delay releases its concurrency slot for visible pages", () => {
  const f = fixture({ concurrency: 1 }); const a = f.image(0); const b = f.image(1);
  f.visible(a, b); a.fail();
  assert.equal(b.requests.length, 1);
  assert.equal(a.requests.length, 1);
});

test("disconnected pages are skipped without consuming a request slot", async () => {
  const f = fixture({ concurrency: 1 }); const a = f.image(0); const b = f.image(1); const c = f.image(2);
  f.visible(a); const pending = f.loader.ensure(b); f.visible(c); b.isConnected = false;
  a.succeed();
  assert.equal(await pending, false);
  assert.equal(b.requests.length, 0);
  assert.equal(c.requests.length, 1);
});

test("destroying a chapter cancels retry timers and active image loads", async () => {
  const f = fixture(); const a = f.image(0); const b = f.image(1);
  const first = f.loader.ensure(a); const second = f.loader.ensure(b);
  a.fail(); f.loader.destroy();
  assert.equal(await first, false); assert.equal(await second, false);
  assert.equal(f.disconnected(), true);
  assert.deepEqual(b.removed, ["src"]);
  f.tick();
  assert.equal(a.requests.length, 1);
  assert.equal(await f.loader.ensure(a), false);
});

test("invalid dimensions cannot create a negative or nonfinite page layout", () => {
  for (const size of [null, {}, { width: -1, height: 10 }, { width: 720, height: Infinity }, { width: NaN, height: 10 }]) assert.equal(Boolean(validSize(size)), false);
  assert.equal(validSize({ width: 720, height: 1600 }), true);
});
