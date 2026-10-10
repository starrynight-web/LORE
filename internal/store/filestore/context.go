package filestore

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/DJRCX/lore/internal/lineage"
	"github.com/DJRCX/lore/internal/present"
	"github.com/DJRCX/lore/internal/result"
	"github.com/DJRCX/lore/internal/store"
	"github.com/DJRCX/lore/internal/text"
	"github.com/DJRCX/lore/internal/tokens"
)

func (s *FileStore) asOf(date string) (time.Time, string, error) {
	if date == "" {
		now := s.now()
		return now, now.Format(time.RFC3339), nil
	}
	t, err := time.ParseInLocation("2006-01-02", date, s.now().Location())
	if err != nil {
		return time.Time{}, "", fmt.Errorf("as_of %q is not a date; use YYYY-MM-DD", date)
	}
	return t, t.Format(time.RFC3339), nil
}

func plural(n int, one, many string) string {
	if n == 1 {
		return "1 " + one
	}
	return fmt.Sprintf("%d %s", n, many)
}

// contextSummary is the deterministic headline (FR-PRS-08).
func contextSummary(env *result.Envelope, subject string) string {
	if subject == "" {
		subject = "this task"
	}
	if env.Verdict == result.NoKnowledge {
		return "No governed rules apply to " + subject + "."
	}
	inConflict := map[string]bool{}
	open := 0
	for _, c := range env.Conflicts {
		if c.Status == "open" {
			open++
			inConflict[c.Left], inConflict[c.Right] = true, true
		}
	}
	rules, skills := 0, 0
	for _, it := range env.Items {
		if inConflict[it.ID] {
			continue
		}
		if it.Kind == result.KindRule {
			rules++
		} else {
			skills++
		}
	}
	var parts []string
	if rules > 0 {
		parts = append(parts, plural(rules, "rule", "rules"))
	}
	if skills > 0 {
		parts = append(parts, plural(skills, "skill", "skills"))
	}
	head := strings.Join(parts, " and ")
	verb := " apply to "
	if rules+skills == 1 {
		verb = " applies to "
	}
	if head == "" {
		head, verb = "Only conflicting rules", " apply to "
	}
	s := head + verb + subject
	if open > 0 {
		s += "; " + plural(open, "conflict must", "conflicts must") + " be resolved"
	}
	return s + "."
}

func (s *FileStore) Context(ctx context.Context, req store.ContextRequest) (*result.Envelope, error) {
	if strings.TrimSpace(req.FilePath) == "" && strings.TrimSpace(req.Intent) == "" {
		return nil, errors.New("file_path and task_intent are both empty; pass the file you are about to edit and one sentence describing the change")
	}
	asOf, asOfStr, err := s.asOf(req.AsOf)
	if err != nil {
		return nil, err
	}
	sn := s.current()
	file := s.normPath(req.FilePath)
	q := text.Terms(req.Intent + " " + strings.ReplaceAll(file, "/", " "))

	env := result.New("get_context")
	env.Task = &result.Task{File: file, Intent: req.Intent}
	env.AsOf = asOfStr
	env.Constants = s.constants()

	sel := s.selectItems(sn, sn.matchComponents(file), q, asOf)
	env.Conflicts = s.attachConflicts(sn, sel, asOf, false)
	env.Excluded = sel.excluded
	rankCandidates(sel.cands)

	switch {
	case len(sel.cands) == 0:
		env.SetVerdict(result.NoKnowledge)
	case len(env.Conflicts) > 0:
		env.SetVerdict(result.Conflict)
	case sel.notes:
		env.SetVerdict(result.OKWithNotes)
	default:
		env.SetVerdict(result.OK)
	}
	return s.finish(env, sn, sel, file, req.Detailed, req.DryRun, func() string { return contextSummary(env, file) })
}

// finish fits the budget, writes the decision record and fills links.
func (s *FileStore) finish(env *result.Envelope, sn *snapshot, sel *selection, file string, detailed, dryRun bool, summary func() string) (*result.Envelope, error) {
	env.Summary = summary()
	dropped := s.fit(sn, env, sel.cands, detailed)
	env.Summary = summary()
	if !dryRun {
		rec := &lineage.Record{
			Tool: env.Tool, Task: env.Task, File: file, Verdict: env.Verdict, Directive: env.Directive,
			Excluded:  append(append([]lineage.ExcludedRef{}, sel.exRefs...), dropped...),
			Constants: env.Constants, GraphSnapshot: sn.hash, ConfidenceMode: env.Constants.ConfidenceMode,
			CreatedAt: env.AsOf, Summary: env.Summary,
		}
		for i, it := range env.Items {
			rec.Used = append(rec.Used, lineage.UsedRef{ID: it.ID, Rank: i + 1})
		}
		for _, c := range env.Conflicts {
			rec.Conflicts = append(rec.Conflicts, c.ID)
		}
		id, err := s.rec.Write(rec)
		if err != nil {
			return nil, fmt.Errorf("record decision: %w", err)
		}
		env.DecisionID = id
	}
	env.Links = links(env)
	env.Budget.Used = tokens.Count(present.AgentText(env, detailed))
	return env, nil
}

// diffFile finds the target path in a unified diff header.
func diffFile(diff string) string {
	for _, l := range strings.Split(diff, "\n") {
		if strings.HasPrefix(l, "+++ ") {
			p := strings.TrimSpace(strings.TrimPrefix(l, "+++ "))
			p = strings.TrimPrefix(p, "b/")
			if p != "/dev/null" {
				return p
			}
		}
	}
	return ""
}

func addedLines(diff string) string {
	var b strings.Builder
	for _, l := range strings.Split(diff, "\n") {
		if strings.HasPrefix(l, "+") && !strings.HasPrefix(l, "+++") {
			b.WriteString(l[1:])
			b.WriteByte('\n')
			if b.Len() > 4000 {
				break
			}
		}
	}
	return b.String()
}

// maxCheckedFileBytes caps how much of a file check_compliance reads when no diff is given.
const maxCheckedFileBytes = 1 << 20

// readProjectFile reads a root-relative file, refusing paths outside the project root.
func (s *FileStore) readProjectFile(rel string) ([]byte, error) {
	if rel == "" || filepath.IsAbs(rel) || rel == ".." || strings.HasPrefix(rel, "../") {
		return nil, fmt.Errorf("%q is outside the project", rel)
	}
	f, err := os.Open(filepath.Join(s.root, filepath.FromSlash(rel)))
	if err != nil {
		return nil, err
	}
	defer f.Close()
	return io.ReadAll(io.LimitReader(f, maxCheckedFileBytes))
}

// asAdded renders content as the added lines of a diff, so a whole file is checked like new code.
func asAdded(content []byte) string {
	lines := strings.Split(string(content), "\n")
	for i, l := range lines {
		lines[i] = "+" + l
	}
	return strings.Join(lines, "\n")
}

func (s *FileStore) Compliance(ctx context.Context, req store.ComplianceRequest) (*result.Envelope, error) {
	asOf, asOfStr, err := s.asOf("")
	if err != nil {
		return nil, err
	}
	sn := s.current()
	file := s.normPath(req.FilePath)
	diff, refPrefix := req.Diff, "sha256:"
	if strings.TrimSpace(diff) == "" {
		if file == "" {
			return nil, errors.New("pass diff (a unified diff of your change), or file_path to check the file as it is now, e.g. when the project has no git repository")
		}
		data, err := s.readProjectFile(file)
		if err != nil {
			return nil, fmt.Errorf("cannot read %s (%v); pass a repo-relative file_path or a diff", file, err)
		}
		diff, refPrefix = asAdded(data), "file:sha256:"
	}
	if file == "" {
		file = s.normPath(diffFile(diff))
	}
	sum := sha256.Sum256([]byte(diff))
	env := result.New("check_compliance")
	env.Task = &result.Task{File: file, DiffRef: refPrefix + hex.EncodeToString(sum[:])[:12]}
	env.AsOf = asOfStr
	env.Constants = s.constants()

	q := text.Terms(addedLines(diff) + " " + strings.ReplaceAll(file, "/", " "))
	sel := s.selectItems(sn, sn.matchComponents(file), q, asOf)
	kept := sel.cands[:0]
	for _, c := range sel.cands {
		if c.doc.Front.Type == "rule" && (c.doc.Front.Modality == "must" || c.doc.Front.Modality == "must_not") {
			kept = append(kept, c)
		}
	}
	sel.cands = kept
	env.Conflicts = s.attachConflicts(sn, sel, asOf, false)
	env.Excluded = sel.excluded
	env.Violations = []result.RuleViolation{}
	rankCandidates(sel.cands)

	switch {
	case len(sel.cands) == 0:
		env.SetVerdict(result.NoKnowledge)
	case len(env.Conflicts) > 0:
		env.SetVerdict(result.Conflict)
	default:
		// Deciding whether a diff breaks a rule needs the Jev `violates` check.
		env.SetVerdict(result.Abstain)
	}
	subject := file
	if subject == "" {
		subject = "this change"
	}
	checked := "the change"
	if refPrefix == "file:sha256:" {
		checked = "the file as it is now"
	}
	return s.finish(env, sn, sel, file, req.Detailed, req.DryRun, func() string {
		switch env.Verdict {
		case result.NoKnowledge:
			return "No MUST rules apply to " + subject + "."
		case result.Conflict:
			return contextSummary(env, subject)
		default:
			return fmt.Sprintf("%s apply to %s; Lore cannot check them automatically yet (no Jev checker), so review %s against each one.",
				plural(len(env.Items), "MUST rule", "MUST rules"), subject, checked)
		}
	})
}
