(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.WebtoonReaderPosition = api;
})(typeof window === "object" ? window : this, function () {
  function pageNumber(value) {
    return Number.isInteger(value) && value >= 0 ? value : 0;
  }

  function pageOffset(value) {
    return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1 ? value : 0;
  }

  function result(chapterId, pageIndex, offset) {
    const result = { chapterId, pageIndex: pageNumber(pageIndex) };
    const fraction = pageOffset(offset);
    if (fraction > 0) result.pageOffset = fraction;
    return result;
  }

  async function resolve({ seriesId, chapterId, pageIndex, pageOffset: offset, fetcher }) {
    if (!seriesId) throw new Error("series is required");
    if (chapterId) return result(chapterId, pageIndex, offset);
    const response = await fetcher(`/api/series/${encodeURIComponent(seriesId)}/continue`);
    if (!response.ok) throw new Error("reading position unavailable");
    const position = await response.json();
    if (typeof position.chapter_id !== "string" || !position.chapter_id) {
      throw new Error("reading position has no chapter");
    }
    return result(position.chapter_id, position.page_index, position.page_offset);
  }

  return { resolve, pageOffset };
});
