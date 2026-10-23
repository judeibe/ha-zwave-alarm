/**
 * Stops the page behind a modal from scrolling. `<dialog>.showModal()` does not do this on iOS Safari, and
 * `overflow: hidden` on <body> alone fails there, so we also pin the body (restoring the scroll position) and
 * lock every scrollable ancestor of the panel, since HA scrolls an inner element rather than the window.
 */
export function lockScroll(from: Element): () => void {
  const restore: (() => void)[] = [];
  const lock = (el: HTMLElement, props: Record<string, string>) => {
    const prev = Object.fromEntries(Object.keys(props).map((k) => [k, el.style.getPropertyValue(k)]));
    for (const [k, v] of Object.entries(props)) el.style.setProperty(k, v);
    restore.push(() => {
      for (const [k, v] of Object.entries(prev)) v ? el.style.setProperty(k, v) : el.style.removeProperty(k);
    });
  };
  for (let el = from.parentElement; el && el !== document.body; el = el.parentElement) {
    const { overflowY } = getComputedStyle(el);
    if ((overflowY === "auto" || overflowY === "scroll") && el.scrollHeight > el.clientHeight) lock(el, { overflow: "hidden" });
  }
  const y = window.scrollY;
  lock(document.body, { position: "fixed", top: `-${y}px`, left: "0", right: "0", overflow: "hidden" });
  restore.push(() => window.scrollTo(0, y));
  return () => restore.reverse().forEach((fn) => fn());
}
