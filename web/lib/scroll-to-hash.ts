/** Sticky header (+ optional banner) clearance for in-page anchors. */
export const HASH_SCROLL_MARGIN_PX = 112

export function scrollToHash(hash: string, behavior: ScrollBehavior = "smooth") {
  const id = hash.replace(/^#/, "")
  if (!id) return false

  const el = document.getElementById(id)
  if (!el) return false

  // Manual offset so sticky header never covers the target (more reliable than scroll-margin alone)
  const top = el.getBoundingClientRect().top + window.scrollY - HASH_SCROLL_MARGIN_PX
  window.scrollTo({ top: Math.max(0, top), behavior })
  history.replaceState(null, "", `#${id}`)

  if (!el.hasAttribute("tabindex")) {
    el.setAttribute("tabindex", "-1")
  }
  el.focus({ preventScroll: true })

  // Nudge again after layout/fonts (reveal + sticky banner height)
  window.setTimeout(() => {
    const again = el.getBoundingClientRect().top + window.scrollY - HASH_SCROLL_MARGIN_PX
    if (Math.abs(window.scrollY - again) > 8) {
      window.scrollTo({ top: Math.max(0, again), behavior: "auto" })
    }
  }, 120)

  return true
}

export function getHashFromHref(href: string): string | null {
  const i = href.indexOf("#")
  if (i === -1) return null
  const hash = href.slice(i + 1).split("?")[0]
  return hash || null
}
