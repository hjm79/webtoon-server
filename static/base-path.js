(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.WebtoonPaths = api.create({
    basePath: document.querySelector('meta[name="webtoon-base-path"]').content,
    pathname: location.pathname,
    fetcher: window.fetch.bind(window),
  });
})(typeof window === "object" ? window : this, function () {
  function create({ basePath = "", pathname = "/", fetcher }) {
    const localPath = basePath && (pathname === basePath || pathname.startsWith(basePath + "/"))
      ? pathname.slice(basePath.length) || "/" : pathname;
    const match = localPath.match(/^\/p\/([^/]+)(?:\/|$)/);
    const profileToken = match ? match[1] : null;
    function appPath(path) {
      if (basePath && (path === basePath || path.startsWith(basePath + "/"))) return path;
      return basePath + path;
    }
    function path(value) {
      if (profileToken && !value.startsWith("/p/")) value = `/p/${profileToken}${value}`;
      return appPath(value);
    }
    function fetch(input, options) {
      return fetcher(typeof input === "string" && input.startsWith("/api/") ? path(input) : input, options);
    }
    return { basePath, profileToken, appPath, path, fetch };
  }
  return { create };
});
