/** Small DOM helpers of the design system. */

/** The text direction that applies to an element: its nearest `dir` attribute, else the document's. */
export function isRtl(el: Element | null | undefined): boolean {
  const dir = (el?.closest("[dir='rtl'], [dir='ltr']") as HTMLElement | null)?.getAttribute("dir")
    ?? (typeof document !== "undefined" ? document.documentElement.getAttribute("dir") : null);
  return dir === "rtl";
}
