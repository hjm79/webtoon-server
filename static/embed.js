(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.WebtoonReaderEmbed = api;
})(typeof window === "object" ? window : this, function () {
  const SOURCE = "webtoon-reader";
  const VERSION = 1;

  function createBridge({ window: win, parentOrigin, allowedOrigins, onClose }) {
    let originIsExact = false;
    try {
      const parsed = new URL(parentOrigin);
      originIsExact = ["http:", "https:"].includes(parsed.protocol) && parsed.origin === parentOrigin;
    } catch (_) {
      originIsExact = false;
    }
    const active = win.parent !== win && originIsExact && Array.isArray(allowedOrigins)
      && allowedOrigins.includes(parentOrigin);
    let closing = false;

    function post(type, payload = {}) {
      if (!active) return;
      win.parent.postMessage({ ...payload, source: SOURCE, version: VERSION, type }, parentOrigin);
    }

    async function receive(event) {
      if (!active || event.source !== win.parent || event.origin !== parentOrigin) return;
      const data = event.data;
      if (!data || data.source !== "webtoon-manager" || data.version !== VERSION || data.type !== "close" || closing) return;
      closing = true;
      try {
        await onClose();
      } finally {
        closing = false;
      }
    }

    if (active) win.addEventListener("message", receive);
    return { active, post, destroy: () => win.removeEventListener("message", receive) };
  }

  return { createBridge };
});
