(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.WebtoonReaderPosition = api;
})(typeof window === "object" ? window : this, function () {
  function pageNumber(value) {
    return Number.isInteger(value) && value >= 0 ? value : 0;
  }

  async function resolve({ seriesId, chapterId, pageIndex, fetcher }) {
    if (!seriesId) throw new Error("series is required");
    if (chapterId) return { chapterId, pageIndex: pageNumber(pageIndex) };
    const response = await fetcher(`/api/series/${encodeURIComponent(seriesId)}/continue`);
    if (!response.ok) throw new Error("reading position unavailable");
    const position = await response.json();
    if (typeof position.chapter_id !== "string" || !position.chapter_id) {
      throw new Error("reading position has no chapter");
    }
    return { chapterId: position.chapter_id, pageIndex: pageNumber(position.page_index) };
  }

  return { resolve };
});
