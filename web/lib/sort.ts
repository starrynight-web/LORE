export type SkillSort = "name-asc" | "name-desc" | "status"

export const SKILL_SORT_OPTIONS: { label: string; value: SkillSort }[] = [
  { label: "A–Z", value: "name-asc" },
  { label: "Z–A", value: "name-desc" },
  { label: "Drafts first", value: "status" },
]

type Sortable = {
  title: string
  status: string
}

export function sortBySkillOption<T extends Sortable>(rows: T[], sort: SkillSort): T[] {
  const copy = [...rows]
  copy.sort((left, right) => {
    if (sort === "status") {
      const leftDraft = left.status === "stable" ? 1 : 0
      const rightDraft = right.status === "stable" ? 1 : 0
      if (leftDraft !== rightDraft) return leftDraft - rightDraft
      return left.title.localeCompare(right.title, undefined, { sensitivity: "base" })
    }
    const compared = left.title.localeCompare(right.title, undefined, { sensitivity: "base" })
    return sort === "name-desc" ? -compared : compared
  })
  return copy
}

export function statusLabel(status: string): string {
  return status === "stable" ? "Ready" : "Draft"
}
