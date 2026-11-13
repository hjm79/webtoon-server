(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.WebtoonReaderImages = api;
})(typeof window === "object" ? window : this, function () {
  function validSize(value) {
    return value && Number.isFinite(value.width) && Number.isFinite(value.height)
      && value.width > 0 && value.height > 0;
  }

  function createLoader({ observerFactory, concurrency = 3, maxRetries = 2,
                          schedule = setTimeout, cancel = clearTimeout,
                          onLoaded = () => {}, onFailed = () => {} }) {
    const records = new Map();
    const queue = [];
    let active = 0;
    let disposed = false;
    const observer = observerFactory((entries) => {
      for (const entry of entries) if (entry.isIntersecting) ensure(entry.target);
    }, { rootMargin: "1200px 0px" });

    function finish(record, success) {
      if (record.state === "loading") active--;
      record.state = success ? "loaded" : "failed";
      if (success) onLoaded(record.img);
      else if (!disposed && record.img.isConnected) onFailed(record.img, () => retry(record.img));
      record.resolve?.(success);
      record.resolve = null;
      drain();
    }

    function start(record) {
      record.state = "loading";
      active++;
      const img = record.img;
      img.onload = () => {
        if (disposed || record.state !== "loading") return;
        if (!img.naturalWidth || !img.naturalHeight) return fail();
        img.dataset.imageState = "loaded";
        img.style.aspectRatio = `${img.naturalWidth} / ${img.naturalHeight}`;
        finish(record, true);
      };
      const fail = () => {
        if (disposed || record.state !== "loading") return;
        if (record.attempts++ < maxRetries) {
          active--;
          record.state = "waiting";
          record.timer = schedule(() => {
            record.timer = null;
            if (disposed || !img.isConnected) {
              record.state = "failed";
              record.resolve?.(false);
              record.resolve = null;
              return;
            }
            record.state = "queued";
            queue.push(record);
            drain();
          }, 750 * record.attempts);
          drain();
        } else {
          img.dataset.imageState = "failed";
          finish(record, false);
        }
      };
      img.onerror = fail;
      img.dataset.imageState = "loading";
      const requestNumber = record.requests++;
      img.src = requestNumber ? `${record.url}${record.url.includes("?") ? "&" : "?"}retry=${requestNumber}` : record.url;
    }

    function drain() {
      while (!disposed && active < concurrency && queue.length) {
        const record = queue.shift();
        if (record.state !== "queued") continue;
        if (!record.img.isConnected) {
          record.state = "failed";
          record.resolve?.(false);
          record.resolve = null;
          continue;
        }
        start(record);
      }
    }

    function ensure(img, { priority = false } = {}) {
      const record = records.get(img);
      if (!record || disposed) return Promise.resolve(false);
      if (record.state === "loaded") return Promise.resolve(true);
      if (record.state === "failed") return Promise.resolve(false);
      if (!record.promise) record.promise = new Promise((resolve) => { record.resolve = resolve; });
      if (record.state === "idle") {
        record.state = "queued";
        if (priority) queue.unshift(record);
        else queue.push(record);
        drain();
      } else if (priority && record.state === "queued") {
        const index = queue.indexOf(record);
        if (index >= 0) queue.splice(index, 1);
        queue.unshift(record);
      }
      return record.promise;
    }

    function retry(img) {
      const record = records.get(img);
      if (!record || disposed || record.state !== "failed") return ensure(img);
      record.attempts = 0;
      record.promise = null;
      record.state = "idle";
      return ensure(img, { priority: true });
    }

    function register(img, url, size) {
      img.dataset.imageState = "idle";
      if (validSize(size)) {
        img.width = size.width;
        img.height = size.height;
        img.style.aspectRatio = `${size.width} / ${size.height}`;
        img.dataset.dimensionsKnown = "true";
      } else {
        img.style.aspectRatio = "3 / 4";
      }
      records.set(img, { img, url, state: "idle", attempts: 0, requests: 0, promise: null, resolve: null, timer: null });
      observer.observe(img);
    }

    function destroy() {
      disposed = true;
      observer.disconnect();
      queue.length = 0;
      for (const record of records.values()) {
        if (record.timer !== null) cancel(record.timer);
        record.img.onload = null;
        record.img.onerror = null;
        if (record.state === "loading") record.img.removeAttribute?.("src");
        record.resolve?.(false);
      }
      records.clear();
    }
    return { register, ensure, retry, destroy };
  }
  return { createLoader, validSize };
});
