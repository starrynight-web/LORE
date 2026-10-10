// Package present renders lore.result/1 envelopes for agents (MCP text block)
// and people (CLI lines). Every surface uses the same badge vocabulary.
package present

import (
	"fmt"
	"sort"
	"strings"

	"github.com/DJRCX/lore/internal/result"
)

// VerdictWords are the human labels shared by GUI and CLI.
var VerdictWords = map[result.Verdict]string{
	result.OK:          "Consistent",
	result.OKWithNotes: "Consistent, with notes",
	result.Conflict:    "Needs your decision",
	result.Abstain:     "Lore can't verify",
	result.NoKnowledge: "No rules apply",
	result.Violation:   "Violation",
	result.Denied:      "Access denied",
}

// ExcludedWords describe each exclusion reason in "Not applied" lines.
var excludedOrder = []struct {
	key  string
	word string
	get  func(result.Excluded) int
}{
	{result.ReasonSuperseded, "superseded", func(e result.Excluded) int { return e.Superseded }},
	{result.ReasonDraft, "draft under review", func(e result.Excluded) int { return e.Draft }},
	{result.ReasonQuarantine, "in quarantine", func(e result.Excluded) int { return e.Quarantine }},
	{result.ReasonOutOfScope, "out of scope", func(e result.Excluded) int { return e.OutOfScope }},
	{result.ReasonStale, "stale", func(e result.Excluded) int { return e.Stale }},
	{result.ReasonLowConfidence, "low confidence", func(e result.Excluded) int { return e.LowConfidence }},
	{result.ReasonDenied, "denied", func(e result.Excluded) int { return e.Denied }},
}

// ExcludedLine renders "1 superseded, 2 draft under review" or "" when nothing was excluded.
func ExcludedLine(e result.Excluded) string {
	var parts []string
	for _, x := range excludedOrder {
		if n := x.get(e); n > 0 {
			parts = append(parts, fmt.Sprintf("%d %s", n, x.word))
		}
	}
	return strings.Join(parts, ", ")
}

// Badges renders the parenthesised badge words for one item.
func Badges(it result.Item, detailed bool) string {
	parts := []string{it.Authority, it.Freshness, it.Confidence.Band}
	if it.Status == "unverified" {
		parts = append([]string{"Unverified"}, parts...)
	}
	if detailed {
		parts = append(parts, fmt.Sprintf("p=%.2f", it.Confidence.P), it.Source.Anchor)
		if it.Source.EffectiveFrom != "" {
			parts = append(parts, "since "+it.Source.EffectiveFrom)
		}
	}
	return strings.Join(nonEmpty(parts), " · ")
}

func nonEmpty(in []string) []string {
	out := in[:0]
	for _, s := range in {
		if s != "" {
			out = append(out, s)
		}
	}
	return out
}

// NextStep is the closing instruction for agents, chosen by verdict.
func NextStep(e *result.Envelope) string {
	switch e.Verdict {
	case result.Conflict:
		return "Next: explain the conflict to the user and ask which rule applies before writing code. Present both sides neutrally; do not pick or recommend one. Cite the rule IDs you follow."
	case result.Abstain:
		return "Next: Lore cannot verify this automatically. Check the change against each rule above yourself and tell the user which ones you checked, citing their IDs."
	case result.Violation:
		return "Next: stop, show the user which rules the change breaks, and propose a fix."
	case result.Denied:
		return "Next: stop; you are not allowed to read this knowledge."
	case result.NoKnowledge:
		return "Next: no governed knowledge applies here; proceed normally."
	default:
		return "Next: follow every MUST rule, prefer the SHOULD guidance, and cite the rule IDs you follow."
	}
}

// AgentText renders the edge-loaded <lore> block: verdict first, next step last.
func AgentText(e *result.Envelope, detailed bool) string {
	var b strings.Builder
	date := e.AsOf
	if len(date) >= 10 {
		date = date[:10]
	}
	fmt.Fprintf(&b, "<lore verdict=%q directive=%q", e.Verdict, e.Directive)
	if e.DecisionID != "" {
		fmt.Fprintf(&b, " decision=%q", e.DecisionID)
	}
	fmt.Fprintf(&b, " as_of=%q tool=%q>\n", date, e.Tool)
	if e.Task != nil && (e.Task.Intent != "" || e.Task.File != "") {
		fmt.Fprintf(&b, "Task: %s\n", strings.Join(nonEmpty([]string{e.Task.Intent, e.Task.File}), " · "))
	}
	fmt.Fprintf(&b, "%s\n", e.Summary)

	inConflict := map[string]bool{}
	for _, c := range e.Conflicts {
		if c.Status == "open" {
			inConflict[c.Left] = true
			inConflict[c.Right] = true
		}
	}
	byID := map[string]result.Item{}
	for _, it := range e.Items {
		byID[it.ID] = it
	}

	n := 0
	section := func(title string, keep func(result.Item) bool) {
		var lines []string
		for _, it := range e.Items {
			if inConflict[it.ID] || !keep(it) {
				continue
			}
			n++
			lines = append(lines, fmt.Sprintf("%d. [%s] %s (%s)", n, it.ID, oneLine(it.Text), Badges(it, detailed)))
		}
		if len(lines) > 0 {
			fmt.Fprintf(&b, "\n%s\n%s\n", title, strings.Join(lines, "\n"))
		}
	}
	isChunk := func(it result.Item) bool { return it.Kind == result.KindChunk }
	section("MUST", func(it result.Item) bool {
		return !isChunk(it) && (it.Modality == "must" || it.Modality == "must_not")
	})

	if len(e.Conflicts) > 0 {
		b.WriteString("\nCONFLICT — do not resolve yourself\n")
		for _, c := range e.Conflicts {
			fmt.Fprintf(&b, "- [%s] %s\n  vs [%s] %s\n  %s\n",
				c.Left, conflictSide(byID, c.Left), c.Right, conflictSide(byID, c.Right), conflictMeta(c))
		}
	}

	section("SHOULD", func(it result.Item) bool {
		return !isChunk(it) && (it.Modality == "should" || it.Modality == "may" || it.Modality == "")
	})
	section("UNVERIFIED (search only; not governing)", isChunk)

	if len(e.Violations) > 0 {
		b.WriteString("\nVIOLATIONS\n")
		for _, v := range e.Violations {
			fmt.Fprintf(&b, "- [%s] %s · p=%.2f · %s\n", v.RuleID, v.Severity, v.P, strings.Join(v.Evidence, ", "))
		}
	}

	if line := dataLines(e); line != "" {
		fmt.Fprintf(&b, "\n%s\n", line)
	}
	if ex := ExcludedLine(e.Excluded); ex != "" {
		fmt.Fprintf(&b, "\nNot applied: %s.\n", ex)
	}
	fmt.Fprintf(&b, "%s\n</lore>", NextStep(e))
	return b.String()
}

func conflictSide(byID map[string]result.Item, id string) string {
	it, ok := byID[id]
	if !ok {
		return "(not in this result; see " + linkFor(id) + ")"
	}
	date := it.Source.EffectiveFrom
	if len(date) >= 7 {
		date = date[:7]
	}
	return fmt.Sprintf("%q (%s)", oneLine(it.Text), strings.Join(nonEmpty([]string{it.Authority, date}), " · "))
}

func conflictMeta(c result.ConflictSummary) string {
	parts := []string{fmt.Sprintf("%s · kind=%s · severity=%s · %s", c.ID, c.Kind, c.Severity, c.Status)}
	if c.ScopeOverlap != "" {
		parts = append(parts, "overlap: "+c.ScopeOverlap)
	}
	if c.Owner != "" {
		parts = append(parts, "owner: "+c.Owner)
	}
	return strings.Join(parts, " · ")
}

// dataLines summarises the optional data payload in one or two lines.
func dataLines(e *result.Envelope) string {
	if len(e.Data) == 0 {
		return ""
	}
	keys := make([]string, 0, len(e.Data))
	for k := range e.Data {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	var parts []string
	for _, k := range keys {
		switch v := e.Data[k].(type) {
		case []any:
			parts = append(parts, fmt.Sprintf("%s: %d entries", k, len(v)))
		case map[string]any:
			parts = append(parts, fmt.Sprintf("%s: %d fields", k, len(v)))
		case string, int, float64, bool:
			parts = append(parts, fmt.Sprintf("%s: %v", k, v))
		default:
			parts = append(parts, k)
		}
	}
	return "Data (full detail in structured content): " + strings.Join(parts, "; ")
}

func oneLine(s string) string {
	s = strings.Join(strings.Fields(s), " ")
	const max = 240
	if len(s) > max {
		s = s[:max-1] + "…"
	}
	return s
}

func linkFor(id string) string {
	switch {
	case strings.HasPrefix(id, "rule:"):
		return "lore://rules/" + strings.TrimPrefix(id, "rule:")
	case strings.HasPrefix(id, "skill:"):
		return "lore://skills/" + strings.TrimPrefix(id, "skill:")
	default:
		return id
	}
}

// CLIText renders human lines for a terminal.
func CLIText(e *result.Envelope) string {
	var b strings.Builder
	head := strings.ToUpper(VerdictWords[e.Verdict])
	rules, conflicts := 0, 0
	for _, it := range e.Items {
		if it.Kind != result.KindChunk {
			rules++
		}
	}
	for _, c := range e.Conflicts {
		if c.Status == "open" {
			conflicts++
		}
	}
	fmt.Fprintf(&b, "%s  %s  %d items · %d conflicts · %d/%d tokens\n", head, e.DecisionID, rules, conflicts, e.Budget.Used, e.Budget.Limit)
	fmt.Fprintf(&b, "  %s\n", e.Summary)
	for _, it := range e.Items {
		label := strings.ToUpper(strings.ReplaceAll(it.Modality, "_", " "))
		if it.Kind == result.KindChunk {
			label = "UNVERIFIED"
		}
		if label == "" {
			label = strings.ToUpper(it.Kind)
		}
		fmt.Fprintf(&b, "  %-10s %-36s %s\n", label, it.ID, Badges(it, false))
	}
	for _, c := range e.Conflicts {
		fmt.Fprintf(&b, "  CONFLICT %s/%s  %s ↔ %s  owner %s\n", c.Kind, c.Severity, c.Left, c.Right, c.Owner)
	}
	if ex := ExcludedLine(e.Excluded); ex != "" {
		fmt.Fprintf(&b, "  not applied: %s\n", ex)
	}
	if e.DecisionID != "" {
		fmt.Fprintf(&b, "→ lore trace %s\n", e.DecisionID)
	}
	return b.String()
}
