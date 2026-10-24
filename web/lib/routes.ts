export function personaHref(id: string) {
  return `/personas/${encodeURIComponent(id)}`
}

export function skillHref(id: string) {
  return `/skills/${id.split("/").map((part) => encodeURIComponent(part)).join("/")}`
}

export function codebaseHref(id: string) {
  return `/codebase/${encodeURIComponent(id)}`
}
