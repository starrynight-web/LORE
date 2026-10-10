package filestore

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/starrynight-web/LORE/internal/chunk"
	"github.com/starrynight-web/LORE/internal/okf"
	"github.com/starrynight-web/LORE/internal/present"
	"github.com/starrynight-web/LORE/internal/result"
	"github.com/starrynight-web/LORE/internal/store"
	"github.com/starrynight-web/LORE/internal/text"
	"github.com/starrynight-web/LORE/internal/tokens"
)

// newEnv starts an envelope for tools that do not write a decision record.
func (s *FileStore) newEnv(tool string) *result.Envelope {
	env := result.New(tool)
	env.AsOf = s.now().Format(time.RFC3339)
	env.Constants = s.constants()
	return env
}

// seal fills links and trims trailing items until the agent text fits the budget.
func (s *FileStore) seal(env *result.Envelope) *result.Envelope {
	for {
		env.Links = links(env)
		used := tokens.Count(present.AgentText(env, false))
		env.Budget = result.Budget{Limit: s.cfg.TokenBudget, Used: used}
		if used <= s.cfg.TokenBudget || len(env.Items) == 0 {
			return env
		}
		env.Items = env.Items[:len(env.Items)-1]
	}
}

func (s *FileStore) Conflicts(ctx context.Context, req store.ConflictsRequest) (*result.Envelope, error) {
	sn := s.current()
	asOf := s.now()
	status := req.Status
	if status == "" {
		status = "open"
	}
	if status != "open" && status != "all" {
		return nil, fmt.Errorf("status %q is not supported; use open or all", req.Status)
	}
	var scope map[string]bool
	scopeLabel := "the whole bundle"
	if req.Scope != "" {
		scopeLabel = req.Scope
		if strings.HasPrefix(req.Scope, "component:") {
			if sn.byID[req.Scope] == nil {
				return nil, fmt.Errorf("unknown component %s; call stats to list components", req.Scope)
			}
			scope = map[string]bool{req.Scope: true}
		} else {
			scope = sn.matchComponents(s.normPath(req.Scope)).specific
		}
	}
	env := s.newEnv("detect_conflicts")
	added := map[string]bool{}
	open := 0
	for _, cd := range sn.conflicts {
		st := cd.Front.Status
		if st == "" {
			st = "open"
		}
		if status == "open" && st != "open" {
			continue
		}
		left, right := sn.byID[cd.Front.LeftRule], sn.byID[cd.Front.RightRule]
		if scope != nil && !touches(left, scope) && !touches(right, scope) {
			continue
		}
		env.Conflicts = append(env.Conflicts, conflictSummary(cd, st))
		if st == "open" {
			open++
		}
		for _, d := range []*okf.Doc{left, right} {
			if d != nil && !added[d.ID] && sn.inactiveReason(d, asOf) == "" {
				added[d.ID] = true
				env.Items = append(env.Items, sn.itemFor(&candidate{doc: d, role: result.RoleConstrains, p: pScoped}))
			}
		}
	}
	switch {
	case open > 0:
		env.SetVerdict(result.Conflict)
		env.Summary = fmt.Sprintf("%s in %s.", plural(open, "open conflict", "open conflicts"), scopeLabel)
	case len(env.Conflicts) > 0:
		env.SetVerdict(result.OK)
		env.Summary = fmt.Sprintf("No open conflicts in %s; %s resolved or dismissed.", scopeLabel, plural(len(env.Conflicts), "conflict", "conflicts"))
	default:
		env.SetVerdict(result.NoKnowledge)
		env.Summary = "No conflicts recorded for " + scopeLabel + "."
	}
	return s.seal(env), nil
}

func touches(d *okf.Doc, scope map[string]bool) bool {
	if d == nil {
		return false
	}
	for _, c := range d.Front.AppliesTo {
		if scope[c] {
			return true
		}
	}
	return false
}

func (s *FileStore) Skill(ctx context.Context, name string) (*result.Envelope, error) {
	name = strings.TrimSpace(name)
	if name == "" {
		return nil, errors.New("name is empty; pass a skill name such as error-wrapping or an id such as skill:go/error-wrapping@v2")
	}
	sn := s.current()
	asOf := s.now()
	want := strings.TrimPrefix(strings.ToLower(name), "skill:")
	wantBase, _ := okf.SplitVersion("skill:" + want)
	var matches []*okf.Doc
	for _, d := range sn.items {
		if d.Front.Type != "skill" {
			continue
		}
		base, _ := okf.SplitVersion(d.ID)
		short := base[strings.LastIndex(base, "/")+1:]
		short = strings.TrimPrefix(short, "skill:")
		if strings.EqualFold(d.ID, "skill:"+want) || base == wantBase ||
			strings.EqualFold(short, want) || strings.EqualFold(d.Front.Title, name) {
			matches = append(matches, d)
		}
	}
	env := s.newEnv("get_skill")
	var live *okf.Doc
	for _, d := range matches {
		if sn.inactiveReason(d, asOf) == "" {
			if live == nil || versionOf(d) > versionOf(live) {
				live = d
			}
		} else {
			env.Excluded.Add(sn.inactiveReason(d, asOf))
		}
	}
	if live == nil {
		env.SetVerdict(result.NoKnowledge)
		if len(matches) > 0 {
			env.Summary = fmt.Sprintf("Skill %q exists but no version is live (draft, superseded or stale).", name)
		} else {
			env.Summary = fmt.Sprintf("No skill named %q; use search to find one.", name)
		}
		return s.seal(env), nil
	}
	env.SetVerdict(result.OK)
	env.Items = append(env.Items, sn.itemFor(&candidate{doc: live, role: result.RoleApplies, p: pScoped, aging: s.aging(live, asOf)}))
	data := map[string]any{"versions": versionList(sn, live.ID, asOf)}
	if secs := s.skillSections(sn, live); len(secs) > 0 {
		data["sections"] = secs
	}
	env.Data = data
	env.Summary = fmt.Sprintf("Skill %s: %s Read %s for the full text.", live.ID, live.Text(), LinkFor(live.ID))
	return s.seal(env), nil
}

func versionOf(d *okf.Doc) int {
	_, n := okf.SplitVersion(d.ID)
	return n
}

type sectionRef struct {
	Heading string `json:"heading"`
	Level   int    `json:"level"`
	Anchor  string `json:"anchor"`
}

// skillSections returns the table of contents of an imported skill's SKILL.md.
func (s *FileStore) skillSections(sn *snapshot, d *okf.Doc) []sectionRef {
	src := sn.sources[d.Front.SourceID]
	if src == nil || src.Front.Staged == "" {
		return nil
	}
	raw, err := s.readStaged(src, "SKILL.md")
	if err != nil {
		return nil
	}
	var out []sectionRef
	for _, h := range chunk.Headings(raw, 3) {
		out = append(out, sectionRef{Heading: h.Heading, Level: h.Level, Anchor: fmt.Sprintf("SKILL.md#L%d", h.Line)})
	}
	return out
}

type versionRef struct {
	ID            string `json:"id"`
	Status        string `json:"status"`
	Live          bool   `json:"live"`
	Reason        string `json:"reason,omitempty"`
	EffectiveFrom string `json:"effective_from,omitempty"`
	EffectiveTo   string `json:"effective_to,omitempty"`
	StaleAfter    string `json:"stale_after,omitempty"`
	Supersedes    string `json:"supersedes,omitempty"`
	SupersededBy  string `json:"superseded_by,omitempty"`
}

func versionList(sn *snapshot, id string, asOf time.Time) []versionRef {
	base, _ := okf.SplitVersion(id)
	var out []versionRef
	for _, d := range sn.versions[base] {
		reason := sn.inactiveReason(d, asOf)
		out = append(out, versionRef{
			ID: d.ID, Status: d.Front.Status, Live: reason == "", Reason: reason,
			EffectiveFrom: d.Front.EffectiveFrom, EffectiveTo: d.Front.EffectiveTo, StaleAfter: d.Front.StaleAfter,
			Supersedes: d.Front.Supersedes, SupersededBy: sn.supersededBy[d.ID],
		})
	}
	return out
}

func (s *FileStore) Search(ctx context.Context, req store.SearchRequest) (*result.Envelope, error) {
	q := text.Terms(req.Query)
	if len(q) == 0 {
		return nil, errors.New("query has no searchable words; use specific terms such as rule names, IDs or topics")
	}
	limit := req.Limit
	if limit <= 0 || limit > s.cfg.SearchLimit {
		limit = s.cfg.SearchLimit
	}
	sn := s.current()
	asOf := s.now()
	env := s.newEnv("search")
	env.Task = &result.Task{Intent: req.Query}

	type hit struct {
		item  result.Item
		score int
	}
	var hits []hit
	for _, d := range sn.items {
		if req.Component != "" && !contains(d.Front.AppliesTo, req.Component) {
			continue
		}
		score, _ := sn.relevance(d.ID, q)
		if score == 0 {
			continue
		}
		if reason := sn.inactiveReason(d, asOf); reason != "" {
			env.Excluded.Add(reason)
			continue
		}
		p := pGlobalKeyword
		if score >= 4 {
			p = pScoped
		}
		hits = append(hits, hit{sn.itemFor(&candidate{doc: d, role: result.RoleApplies, p: p, aging: s.aging(d, asOf)}), score * 2})
	}
	if req.IncludeUnverified && req.Component == "" {
		for i := range sn.chunks {
			c := &sn.chunks[i]
			score := c.relevance(q)
			if score == 0 {
				continue
			}
			hits = append(hits, hit{chunkItem(c), score})
		}
	}
	sort.SliceStable(hits, func(i, j int) bool { return hits[i].score > hits[j].score })
	if len(hits) > limit {
		hits = hits[:limit]
	}
	for _, h := range hits {
		env.Items = append(env.Items, h.item)
	}
	if len(env.Items) == 0 {
		env.SetVerdict(result.NoKnowledge)
		env.Summary = fmt.Sprintf("Nothing matches %q.", req.Query)
	} else {
		env.SetVerdict(result.OK)
		unverified := 0
		for _, it := range env.Items {
			if it.Kind == result.KindChunk {
				unverified++
			}
		}
		env.Summary = fmt.Sprintf("%s for %q (%d governed, %d unverified).", plural(len(env.Items), "match", "matches"), req.Query, len(env.Items)-unverified, unverified)
	}
	return s.seal(env), nil
}

func chunkItem(c *chunkRec) result.Item {
	snippet := c.Text
	if c.Heading != "" {
		snippet = c.Heading + ": " + snippet
	}
	snippet = text.FirstSentence(strings.ReplaceAll(snippet, "\n", " "), 220)
	return result.Item{
		ID: c.ID, Kind: result.KindChunk, Role: result.RoleBackground, Authority: "unreviewed",
		Status: "unverified", Freshness: result.FreshCurrent, Origin: "human_authored",
		Confidence: result.Confidence{Band: result.BandMedium, P: 0.60},
		Title:      c.Heading, Text: snippet,
		Source: result.Source{Path: c.Display, Anchor: c.Anchor},
	}
}

func contains(list []string, v string) bool {
	for _, x := range list {
		if x == v {
			return true
		}
	}
	return false
}

func (s *FileStore) History(ctx context.Context, req store.HistoryRequest) (*result.Envelope, error) {
	sn := s.current()
	asOf := s.now()
	env := s.newEnv("get_history")
	var bases []string
	switch {
	case req.ItemID != "":
		base, _ := okf.SplitVersion(req.ItemID)
		if len(sn.versions[base]) == 0 {
			return nil, fmt.Errorf("unknown item %s; ids look like rule:auth/jwt-expiry@v3", req.ItemID)
		}
		bases = []string{base}
	case req.FilePath != "":
		file := s.normPath(req.FilePath)
		env.Task = &result.Task{File: file}
		cm := sn.matchComponents(file)
		seen := map[string]bool{}
		for _, d := range sn.items {
			if touches(d, cm.specific) {
				base, _ := okf.SplitVersion(d.ID)
				if !seen[base] {
					seen[base] = true
					bases = append(bases, base)
				}
			}
		}
		sort.Strings(bases)
	default:
		return nil, errors.New("pass file_path or item_id")
	}
	var chains []map[string]any
	for _, base := range bases {
		vs := versionList(sn, base+"@v0", asOf)
		chains = append(chains, map[string]any{"base": base, "versions": vs})
		for _, d := range sn.versions[base] {
			if sn.inactiveReason(d, asOf) == "" {
				env.Items = append(env.Items, sn.itemFor(&candidate{doc: d, role: result.RoleApplies, p: pScoped, aging: s.aging(d, asOf)}))
			}
		}
	}
	env.Data = map[string]any{"versions": chains}
	if len(chains) == 0 {
		env.SetVerdict(result.NoKnowledge)
		env.Summary = "No versioned knowledge applies here."
	} else {
		env.SetVerdict(result.OK)
		total := 0
		for _, b := range bases {
			total += len(sn.versions[b])
		}
		env.Summary = fmt.Sprintf("%s across %s; %d live.", plural(total, "version", "versions"), plural(len(bases), "item", "items"), len(env.Items))
	}
	return s.seal(env), nil
}

type provNode struct {
	ID     string `json:"id"`
	Kind   string `json:"kind"` // activity | entity | source | agent
	Label  string `json:"label"`
	Reason string `json:"excluded_reason,omitempty"`
}

type provEdge struct {
	From string `json:"from"`
	To   string `json:"to"`
	Rel  string `json:"rel"` // used | excluded | wasDerivedFrom | wasAttributedTo
}

func (s *FileStore) Trace(ctx context.Context, decisionID string) (*result.Envelope, error) {
	rec, err := s.rec.Get(decisionID)
	if err != nil {
		return nil, err
	}
	sn := s.current()
	env := s.newEnv("trace")
	env.Task = rec.Task
	nodes := []provNode{{ID: rec.DecisionID, Kind: "activity", Label: fmt.Sprintf("%s → %s", rec.Tool, rec.Verdict)}}
	var edges []provEdge
	seen := map[string]bool{rec.DecisionID: true}
	addNode := func(n provNode) {
		if !seen[n.ID] {
			seen[n.ID] = true
			nodes = append(nodes, n)
		}
	}
	attach := func(id string) {
		d := sn.byID[id]
		if d == nil {
			return
		}
		if src := sn.sources[d.Front.SourceID]; src != nil {
			addNode(provNode{ID: src.ID, Kind: "source", Label: firstNonEmpty(src.Front.Path, src.Front.Title)})
			edges = append(edges, provEdge{From: id, To: src.ID, Rel: "wasDerivedFrom"})
		}
		if d.Front.Owner != "" {
			addNode(provNode{ID: "agent:" + d.Front.Owner, Kind: "agent", Label: d.Front.Owner})
			edges = append(edges, provEdge{From: id, To: "agent:" + d.Front.Owner, Rel: "wasAttributedTo"})
		}
		if d.Front.Origin != "" && d.Front.Origin != "human_authored" {
			addNode(provNode{ID: "agent:" + d.Front.Origin, Kind: "agent", Label: d.Front.Origin})
			edges = append(edges, provEdge{From: id, To: "agent:" + d.Front.Origin, Rel: "wasAttributedTo"})
		}
	}
	asOf := s.now()
	for _, u := range rec.Used {
		addNode(provNode{ID: u.ID, Kind: "entity", Label: titleOf(sn, u.ID)})
		edges = append(edges, provEdge{From: rec.DecisionID, To: u.ID, Rel: "used"})
		attach(u.ID)
		if d := sn.byID[u.ID]; d != nil && sn.inactiveReason(d, asOf) == "" {
			env.Items = append(env.Items, sn.itemFor(&candidate{doc: d, role: result.RoleApplies, p: pScoped}))
		}
	}
	for _, x := range rec.Excluded {
		addNode(provNode{ID: x.ID, Kind: "entity", Label: titleOf(sn, x.ID), Reason: x.Reason})
		edges = append(edges, provEdge{From: rec.DecisionID, To: x.ID, Rel: "excluded"})
		attach(x.ID)
	}
	for _, cid := range rec.Conflicts {
		for _, cd := range sn.conflicts {
			if cd.ID == cid {
				st := cd.Front.Status
				if st == "" {
					st = "open"
				}
				env.Conflicts = append(env.Conflicts, conflictSummary(cd, st))
			}
		}
	}
	env.SetVerdict(result.OK)
	env.Summary = fmt.Sprintf("%s (%s, verdict %s): %s used, %s excluded; graph snapshot %s.",
		rec.DecisionID, rec.Tool, rec.Verdict, plural(len(rec.Used), "item", "items"), plural(len(rec.Excluded), "item", "items"), rec.GraphSnapshot)
	if rec.GraphSnapshot != sn.hash {
		env.Summary += " The bundle has changed since this decision."
	}
	env.Data = map[string]any{
		"decision":   rec,
		"prov_graph": map[string]any{"nodes": nodes, "edges": edges},
	}
	env = s.seal(env)
	env.Links = append(env.Links, LinkFor(rec.DecisionID))
	return env, nil
}

func titleOf(sn *snapshot, id string) string {
	if d := sn.byID[id]; d != nil && d.Front.Title != "" {
		return d.Front.Title
	}
	return id
}

func firstNonEmpty(a ...string) string {
	for _, s := range a {
		if s != "" {
			return s
		}
	}
	return ""
}

func (s *FileStore) Stats(ctx context.Context) (*result.Envelope, error) {
	sn := s.current()
	asOf := s.now()
	env := s.newEnv("stats")
	byType := map[string]int{}
	byStatus := map[string]int{}
	var drafts, live []string
	for _, d := range sn.items {
		byType[d.Front.Type]++
		reason := sn.inactiveReason(d, asOf)
		if reason == "" {
			byStatus["live"]++
			live = append(live, d.ID)
		} else {
			byStatus[reason]++
		}
		if d.Front.Status == "draft" || d.Front.Status == "quarantine" || d.Front.Status == "" {
			drafts = append(drafts, d.ID)
		}
	}
	openBySeverity := map[string]int{}
	open := 0
	for _, cd := range sn.conflicts {
		if cd.Front.Status == "" || cd.Front.Status == "open" {
			open++
			openBySeverity[firstNonEmpty(cd.Front.Severity, "medium")]++
		}
	}
	var comps []string
	for _, c := range sn.components {
		comps = append(comps, c.ID)
	}
	jobs, _ := s.listJobs()
	jobStates := map[string]int{}
	for _, j := range jobs {
		jobStates[j.State]++
	}
	var loadErrs []string
	for _, e := range sn.loadErrs {
		loadErrs = append(loadErrs, e.Error())
	}
	env.Data = map[string]any{
		"stats": map[string]any{
			"items_by_type":              byType,
			"items_by_state":             byStatus,
			"components":                 comps,
			"sources":                    len(sn.sources),
			"open_conflicts":             open,
			"open_conflicts_by_severity": openBySeverity,
			"unverified_chunks":          len(sn.chunks),
			"decisions":                  len(s.rec.List()),
			"jobs_by_state":              jobStates,
			"graph_snapshot":             sn.hash,
			"load_errors":                loadErrs,
		},
		"drafts": drafts,
	}
	env.SetVerdict(result.OK)
	env.Summary = fmt.Sprintf("%s live, %s awaiting review, %s, %s.",
		plural(len(live), "item", "items"), plural(len(drafts), "draft", "drafts"),
		plural(open, "open conflict", "open conflicts"), plural(len(sn.chunks), "unverified chunk", "unverified chunks"))
	if len(loadErrs) > 0 {
		env.Summary += fmt.Sprintf(" %s could not be parsed.", plural(len(loadErrs), "file", "files"))
	}
	return s.seal(env), nil
}

func (s *FileStore) IngestStatus(ctx context.Context, jobID string) (*result.Envelope, error) {
	jobs, err := s.listJobs()
	if err != nil {
		return nil, err
	}
	env := s.newEnv("ingest_status")
	if jobID != "" {
		var found []job
		for _, j := range jobs {
			if j.JobID == jobID {
				found = append(found, j)
			}
		}
		if len(found) == 0 {
			return nil, fmt.Errorf("job %s not found; call ingest_status without job_id to list jobs", jobID)
		}
		jobs = found
	}
	env.Data = map[string]any{"jobs": jobs}
	if len(jobs) == 0 {
		env.SetVerdict(result.NoKnowledge)
		env.Summary = "No ingest jobs yet."
	} else {
		env.SetVerdict(result.OK)
		states := map[string]int{}
		for _, j := range jobs {
			states[j.State]++
		}
		var parts []string
		for _, st := range []string{"queued", "normalizing", "extracting", "quarantine", "draft", "indexing", "ready", "failed"} {
			if states[st] > 0 {
				parts = append(parts, fmt.Sprintf("%d %s", states[st], st))
			}
		}
		env.Summary = fmt.Sprintf("%s: %s.", plural(len(jobs), "job", "jobs"), strings.Join(parts, ", "))
	}
	return s.seal(env), nil
}
