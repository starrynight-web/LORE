package filestore

import (
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/DJRCX/lore/internal/lineage"
	"github.com/DJRCX/lore/internal/okf"
	"github.com/DJRCX/lore/internal/present"
	"github.com/DJRCX/lore/internal/result"
	"github.com/DJRCX/lore/internal/tokens"
	"github.com/bmatcuk/doublestar/v4"
)

// Placeholder confidences until Jev `applies` replaces them. They are
// deterministic so identical inputs give identical results.
const (
	pScopedKeyword = 0.92
	pScoped        = 0.82
	pExpanded      = 0.70
	pGlobalKeyword = 0.66
)

var modalityOrder = map[string]int{"must": 0, "must_not": 1, "should": 2, "may": 3, "": 4}

var authorityOrder = map[string]int{"policy": 0, "team_convention": 1, "procedure": 2, "reviewed": 3}

type componentMatch struct {
	specific map[string]bool
	global   map[string]bool
}

func (cm componentMatch) any() bool { return len(cm.specific) > 0 }

// matchComponents maps a file path to components by glob. Components whose
// globs include "**" count as global.
func (sn *snapshot) matchComponents(file string) componentMatch {
	cm := componentMatch{specific: map[string]bool{}, global: map[string]bool{}}
	for _, c := range sn.components {
		for _, g := range c.Front.Globs {
			if g == "**" || g == "**/*" {
				cm.global[c.ID] = true
				break
			}
			if file != "" {
				if ok, _ := doublestar.Match(g, file); ok {
					cm.specific[c.ID] = true
					break
				}
			}
		}
	}
	return cm
}

// normPath turns an absolute or ./-prefixed path into a root-relative slash path.
func (s *FileStore) normPath(p string) string {
	if p == "" {
		return ""
	}
	if filepath.IsAbs(p) {
		if rel, err := filepath.Rel(s.root, p); err == nil && !strings.HasPrefix(rel, "..") {
			p = rel
		}
	}
	return strings.TrimPrefix(filepath.ToSlash(filepath.Clean(p)), "./")
}

type candidate struct {
	doc   *okf.Doc
	role  string
	p     float64
	score int
	aging bool
}

type selection struct {
	cands    []*candidate
	excluded result.Excluded
	exRefs   []lineage.ExcludedRef
	notes    bool
}

// relevance scores a doc against query terms: strong hits count double.
func (sn *snapshot) relevance(id string, q []string) (score, strongHits int) {
	st, wk := sn.strong[id], sn.weak[id]
	for _, t := range q {
		switch {
		case st[t]:
			score += 2
			strongHits++
		case wk[t]:
			score++
		}
	}
	return
}

func parseDate(s string) (time.Time, bool) {
	if len(s) < 10 {
		return time.Time{}, false
	}
	t, err := time.Parse("2006-01-02", s[:10])
	return t, err == nil
}

// inactiveReason applies the status and temporal filters. "" means live.
func (sn *snapshot) inactiveReason(d *okf.Doc, asOf time.Time) string {
	switch d.Front.Status {
	case "draft", "":
		return result.ReasonDraft
	case "quarantine":
		return result.ReasonQuarantine
	case "deprecated", "superseded":
		return result.ReasonSuperseded
	}
	if _, ok := sn.supersededBy[d.ID]; ok {
		if succ := sn.byID[sn.supersededBy[d.ID]]; succ != nil && succ.Front.Status == "stable" {
			return result.ReasonSuperseded
		}
	}
	if t, ok := parseDate(d.Front.StaleAfter); ok && asOf.After(t) {
		return result.ReasonStale
	}
	if t, ok := parseDate(d.Front.EffectiveTo); ok && asOf.After(t) {
		return result.ReasonStale
	}
	if t, ok := parseDate(d.Front.EffectiveFrom); ok && asOf.Before(t) {
		return result.ReasonOutOfScope
	}
	return ""
}

func (s *FileStore) aging(d *okf.Doc, asOf time.Time) bool {
	t, ok := parseDate(d.Front.StaleAfter)
	return ok && !asOf.After(t) && t.Sub(asOf) <= time.Duration(s.cfg.AgingWindowDays)*24*time.Hour
}

// selectItems runs component mapping, keyword seeding, filters and graph expansion.
func (s *FileStore) selectItems(sn *snapshot, cm componentMatch, q []string, asOf time.Time) *selection {
	sel := &selection{}
	byID := map[string]*candidate{}
	exclude := func(d *okf.Doc, reason string) {
		sel.excluded.Add(reason)
		sel.exRefs = append(sel.exRefs, lineage.ExcludedRef{ID: d.ID, Reason: reason})
	}
	for _, d := range sn.items {
		score, strong := sn.relevance(d.ID, q)
		scoped, global := false, len(d.Front.AppliesTo) == 0
		for _, c := range d.Front.AppliesTo {
			if cm.specific[c] {
				scoped = true
			}
			if cm.global[c] {
				global = true
			}
		}
		var p float64
		switch {
		case scoped && score > 0:
			p = pScopedKeyword
		case scoped:
			p = pScoped
		case global && strong > 0:
			p = pGlobalKeyword
		case strong > 0:
			// Keyword hit on an item scoped to other components.
			if sn.inactiveReason(d, asOf) == "" {
				exclude(d, result.ReasonOutOfScope)
			}
			continue
		default:
			continue
		}
		if reason := sn.inactiveReason(d, asOf); reason != "" {
			exclude(d, reason)
			if reason == result.ReasonSuperseded {
				sel.notes = true
			}
			continue
		}
		c := &candidate{doc: d, role: result.RoleApplies, p: p, score: score, aging: s.aging(d, asOf)}
		byID[d.ID] = c
	}

	// Graph expansion over depends_on / supported_by / exempts.
	frontier := make([]*candidate, 0, len(byID))
	for _, c := range byID {
		frontier = append(frontier, c)
	}
	for hop := 0; hop < s.cfg.GraphHops && len(frontier) > 0; hop++ {
		var next []*candidate
		for _, c := range frontier {
			if len(c.doc.Front.Exempts) > 0 {
				c.role = result.RoleExempts
				sel.notes = true
			}
			for _, ref := range append(append([]string{}, c.doc.Front.DependsOn...), c.doc.Front.SupportedBy...) {
				if _, seen := byID[ref]; seen {
					continue
				}
				d := sn.byID[ref]
				if d == nil || (d.Front.Type != "rule" && d.Front.Type != "skill" && d.Front.Type != "procedure") {
					continue
				}
				if sn.inactiveReason(d, asOf) != "" {
					continue
				}
				nc := &candidate{doc: d, role: result.RoleBackground, p: pExpanded, aging: s.aging(d, asOf)}
				byID[ref] = nc
				next = append(next, nc)
			}
		}
		frontier = next
	}
	for _, c := range byID {
		if c.aging {
			sel.notes = true
		}
		sel.cands = append(sel.cands, c)
	}
	return sel
}

// attachConflicts adds open conflict records touching the candidates. If the
// other side is active but was not selected it is pulled in as a constraint.
func (s *FileStore) attachConflicts(sn *snapshot, sel *selection, asOf time.Time, includeResolved bool) []result.ConflictSummary {
	in := map[string]*candidate{}
	for _, c := range sel.cands {
		in[c.doc.ID] = c
	}
	var out []result.ConflictSummary
	for _, cd := range sn.conflicts {
		f := cd.Front
		status := f.Status
		if status == "" {
			status = "open"
		}
		if status != "open" && !includeResolved {
			continue
		}
		_, l := in[f.LeftRule]
		_, r := in[f.RightRule]
		if !l && !r {
			continue
		}
		left, right := sn.byID[f.LeftRule], sn.byID[f.RightRule]
		if left == nil || right == nil || sn.inactiveReason(left, asOf) != "" || sn.inactiveReason(right, asOf) != "" {
			// One side is superseded, stale or draft: the conflict no longer blocks.
			sel.notes = true
			continue
		}
		for _, d := range []*okf.Doc{left, right} {
			if _, ok := in[d.ID]; !ok {
				c := &candidate{doc: d, role: result.RoleConstrains, p: pExpanded}
				in[d.ID] = c
				sel.cands = append(sel.cands, c)
			}
		}
		out = append(out, conflictSummary(cd, status))
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out
}

func conflictSummary(cd *okf.Doc, status string) result.ConflictSummary {
	f := cd.Front
	sev := f.Severity
	if sev == "" {
		sev = "medium"
	}
	kind := f.Kind
	if kind == "" {
		kind = "direct"
	}
	return result.ConflictSummary{
		ID: cd.ID, Left: f.LeftRule, Right: f.RightRule, Kind: kind, Severity: sev,
		ScopeOverlap: f.ScopeOverlap, Status: status, Owner: f.Owner,
	}
}

func rankCandidates(cands []*candidate) {
	sort.SliceStable(cands, func(i, j int) bool {
		a, b := cands[i], cands[j]
		if x, y := modalityOrder[a.doc.Front.Modality], modalityOrder[b.doc.Front.Modality]; x != y {
			return x < y
		}
		if x, y := authOrder(a.doc), authOrder(b.doc); x != y {
			return x < y
		}
		if a.p != b.p {
			return a.p > b.p
		}
		if a.score != b.score {
			return a.score > b.score
		}
		return a.doc.ID < b.doc.ID
	})
}

func authOrder(d *okf.Doc) int {
	if n, ok := authorityOrder[d.Front.Authority]; ok {
		return n
	}
	return len(authorityOrder)
}

// itemFor converts a document to an envelope item.
func (sn *snapshot) itemFor(c *candidate) result.Item {
	d := c.doc
	band := result.BandMedium
	if c.p >= 0.80 {
		band = result.BandHigh
	}
	fresh := result.FreshCurrent
	if c.aging {
		fresh = result.FreshAging
	}
	auth := d.Front.Authority
	if _, ok := authorityOrder[auth]; !ok {
		auth = "reviewed"
	}
	origin := d.Front.Origin
	switch origin {
	case "human_authored", "llm_extracted_reviewed", "git_derived":
	default:
		origin = "human_authored"
	}
	path, anchor := d.Front.Anchor, d.Front.Anchor
	if i := strings.Index(path, "#"); i >= 0 {
		path, anchor = path[:i], path[i+1:]
	}
	if src := sn.sources[d.Front.SourceID]; src != nil && src.Front.Path != "" && path == "" {
		path = src.Front.Path
	}
	if path == "" {
		path = ".lore/" + d.Path
	}
	if anchor == "" {
		anchor = "L1"
	}
	modality := d.Front.Modality
	if modality == "" && d.Front.Type == "skill" {
		modality = "should"
	}
	return result.Item{
		ID: d.ID, Kind: d.Front.Type, Modality: modality, Role: c.role, Authority: auth,
		Status: "stable", Freshness: fresh, Origin: origin,
		Confidence: result.Confidence{Band: band, P: c.p},
		Title:      d.Front.Title, Text: d.Text(),
		Source: result.Source{Path: path, Anchor: anchor, EffectiveFrom: d.Front.EffectiveFrom, LastVerified: d.Front.Verified},
	}
}

// LinkFor returns the lore:// URI of an item or conflict ID.
func LinkFor(id string) string {
	switch {
	case strings.HasPrefix(id, "rule:"):
		return "lore://rules/" + strings.TrimPrefix(id, "rule:")
	case strings.HasPrefix(id, "skill:"):
		return "lore://skills/" + strings.TrimPrefix(id, "skill:")
	case strings.HasPrefix(id, "procedure:"):
		return "lore://procedures/" + strings.TrimPrefix(id, "procedure:")
	case strings.HasPrefix(id, "conf-"):
		return "lore://conflicts/" + id
	case strings.HasPrefix(id, "dec-"):
		return "lore://decisions/" + id
	case strings.HasPrefix(id, "src:"):
		return "lore://sources/" + strings.TrimPrefix(id, "src:")
	}
	return ""
}

// fit fills items from ranked candidates, keeping conflict sides, then drops
// the lowest-ranked items until the agent text fits the token budget.
func (s *FileStore) fit(sn *snapshot, env *result.Envelope, cands []*candidate, detailed bool) []lineage.ExcludedRef {
	keep := map[string]bool{}
	for _, c := range env.Conflicts {
		keep[c.Left], keep[c.Right] = true, true
	}
	var chosen []*candidate
	var dropped []lineage.ExcludedRef
	for _, c := range cands {
		if keep[c.doc.ID] || len(chosen) < s.cfg.MaxItems {
			chosen = append(chosen, c)
		} else {
			dropped = append(dropped, lineage.ExcludedRef{ID: c.doc.ID, Reason: "budget"})
		}
	}
	for {
		env.Items = env.Items[:0]
		for _, c := range chosen {
			env.Items = append(env.Items, sn.itemFor(c))
		}
		used := tokens.Count(present.AgentText(env, detailed))
		env.Budget = result.Budget{Limit: s.cfg.TokenBudget, Used: used}
		if used <= s.cfg.TokenBudget {
			return dropped
		}
		cut := -1
		for i := len(chosen) - 1; i >= 0; i-- {
			if !keep[chosen[i].doc.ID] {
				cut = i
				break
			}
		}
		if cut < 0 {
			return dropped
		}
		dropped = append(dropped, lineage.ExcludedRef{ID: chosen[cut].doc.ID, Reason: "budget"})
		chosen = append(chosen[:cut], chosen[cut+1:]...)
	}
}

// links lists resources referenced by the envelope.
func links(env *result.Envelope) []string {
	out := []string{}
	seen := map[string]bool{}
	add := func(id string) {
		if l := LinkFor(id); l != "" && !seen[l] {
			seen[l] = true
			out = append(out, l)
		}
	}
	for _, it := range env.Items {
		if it.Kind != result.KindChunk {
			add(it.ID)
		}
	}
	for _, c := range env.Conflicts {
		add(c.ID)
	}
	if env.DecisionID != "" {
		add(env.DecisionID)
	}
	return out
}
