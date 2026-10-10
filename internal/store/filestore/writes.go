package filestore

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/DJRCX/lore/internal/importer/skills"
	"github.com/DJRCX/lore/internal/lineage"
	"github.com/DJRCX/lore/internal/result"
	"github.com/DJRCX/lore/internal/store"
	"github.com/DJRCX/lore/internal/text"
)

// job is DR-06, minus fields that only exist once a worker is connected.
type job struct {
	JobID     string   `json:"job_id"`
	SourceID  string   `json:"source_id,omitempty"`
	State     string   `json:"state"`
	Attempts  int      `json:"attempts"`
	Kind      string   `json:"kind"`
	Filename  string   `json:"filename,omitempty"`
	Staged    string   `json:"staged,omitempty"`
	Authority string   `json:"authority,omitempty"`
	ItemIDs   []string `json:"item_ids,omitempty"`
	Message   string   `json:"message,omitempty"`
	CreatedAt string   `json:"created_at"`
	UpdatedAt string   `json:"updated_at"`
}

var jobRe = regexp.MustCompile(`^job-(\d+)\.json$`)

func (s *FileStore) jobsDir() string { return filepath.Join(s.loreDir, "_staging", "jobs") }

func (s *FileStore) listJobs() ([]job, error) {
	entries, err := os.ReadDir(s.jobsDir())
	if errors.Is(err, fs.ErrNotExist) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	var out []job
	for _, e := range entries {
		if !jobRe.MatchString(e.Name()) {
			continue
		}
		data, err := os.ReadFile(filepath.Join(s.jobsDir(), e.Name()))
		if err != nil {
			continue
		}
		var j job
		if json.Unmarshal(data, &j) == nil {
			out = append(out, j)
		}
	}
	sort.Slice(out, func(i, k int) bool { return out[i].JobID > out[k].JobID })
	return out, nil
}

// newJob claims the next job ID with O_EXCL and writes the record.
func (s *FileStore) newJob(j job) (job, error) {
	s.jobsMu.Lock()
	defer s.jobsMu.Unlock()
	if err := os.MkdirAll(s.jobsDir(), 0o755); err != nil {
		return j, err
	}
	now := s.now().Format(time.RFC3339)
	j.CreatedAt, j.UpdatedAt = now, now
	for attempt := 0; attempt < 50; attempt++ {
		max := 0
		entries, _ := os.ReadDir(s.jobsDir())
		for _, e := range entries {
			if m := jobRe.FindStringSubmatch(e.Name()); m != nil {
				if n, _ := strconv.Atoi(m[1]); n > max {
					max = n
				}
			}
		}
		j.JobID = fmt.Sprintf("job-%04d", max+1)
		f, err := os.OpenFile(filepath.Join(s.jobsDir(), j.JobID+".json"), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o644)
		if errors.Is(err, fs.ErrExist) {
			continue
		}
		if err != nil {
			return j, err
		}
		data, _ := json.MarshalIndent(j, "", "  ")
		_, err = f.Write(data)
		if cerr := f.Close(); err == nil {
			err = cerr
		}
		return j, err
	}
	return j, errors.New("could not allocate a job id")
}

var validIngestAuthority = map[string]bool{"policy": true, "team_convention": true, "procedure": true, "reviewed": true, "draft": true}

const queuedNote = "queued for normalize and extract; the extraction worker is not connected yet, so it stays queued. Its text is already searchable as Unverified."

func (s *FileStore) Ingest(ctx context.Context, req store.IngestRequest) (*store.Receipt, error) {
	authority := req.Authority
	if authority == "" {
		authority = "draft"
	}
	if !validIngestAuthority[authority] {
		return nil, fmt.Errorf("authority %q is not one of policy, team_convention, procedure, reviewed, draft", req.Authority)
	}
	maxBytes := int64(s.cfg.MaxUploadMB) << 20
	switch {
	case req.Path != "":
		p := req.Path
		if !filepath.IsAbs(p) {
			p = filepath.Join(s.root, p)
		}
		st, err := os.Stat(p)
		if err != nil {
			return nil, fmt.Errorf("cannot read %s: %v; pass a path relative to the project root or an absolute path", req.Path, err)
		}
		if st.IsDir() {
			return s.ingestSkills(p, authority)
		}
		if st.Size() > maxBytes {
			return nil, fmt.Errorf("%s is %d MB; the limit is %d MB", req.Path, st.Size()>>20, s.cfg.MaxUploadMB)
		}
		data, err := os.ReadFile(p)
		if err != nil {
			return nil, err
		}
		return s.stageUpload("uploads", filepath.Base(p), data, authority, "ingest")
	case req.Content != "":
		if req.Filename == "" {
			return nil, errors.New("filename is required with content, e.g. auth-policy.md")
		}
		if int64(len(req.Content)) > maxBytes {
			return nil, fmt.Errorf("content is larger than %d MB", s.cfg.MaxUploadMB)
		}
		return s.stageUpload("uploads", req.Filename, []byte(req.Content), authority, "ingest")
	default:
		return nil, errors.New("pass either path, or content plus filename")
	}
}

func (s *FileStore) ingestSkills(dir, authority string) (*store.Receipt, error) {
	if authority == "draft" {
		authority = "reviewed"
	}
	results, err := skills.Import(s.loreDir, []string{dir}, skills.Options{Stable: false, Authority: authority, Now: s.now})
	if err != nil {
		return nil, err
	}
	var ids, notes []string
	for _, r := range results {
		if r.ID != "" && (r.Action == "imported" || r.Action == "updated") {
			ids = append(ids, r.ID)
		}
		if r.Action != "imported" && r.Action != "updated" {
			notes = append(notes, fmt.Sprintf("%s %s: %s", r.Name, r.Action, r.Note))
		}
	}
	if len(ids) == 0 && len(notes) > 0 {
		return nil, fmt.Errorf("nothing imported from %s: %s", dir, strings.Join(notes, "; "))
	}
	msg := fmt.Sprintf("Imported %s as drafts. A person must run `lore promote <id>` before they reach live context.", plural(len(ids), "skill", "skills"))
	if len(notes) > 0 {
		msg += " Skipped: " + strings.Join(notes, "; ")
	}
	j, err := s.newJob(job{State: "draft", Kind: "skill_import", Authority: authority, ItemIDs: ids, Message: msg, Staged: dir})
	if err != nil {
		return nil, err
	}
	_ = s.Reload()
	return &store.Receipt{JobID: j.JobID, State: j.State, Message: msg, ItemIDs: ids}, nil
}

func safeName(name string) string {
	base := filepath.Base(name)
	ext := filepath.Ext(base)
	stem := text.Slug(strings.TrimSuffix(base, ext))
	if stem == "" {
		stem = "upload"
	}
	ext = strings.ToLower(ext)
	if len(ext) > 10 {
		ext = ""
	}
	return stem + ext
}

func (s *FileStore) stageUpload(sub, filename string, data []byte, authority, kind string) (*store.Receipt, error) {
	j, err := s.newJob(job{State: "queued", Kind: kind, Filename: filename, Authority: authority, Message: queuedNote})
	if err != nil {
		return nil, err
	}
	rel := filepath.ToSlash(filepath.Join("_staging", sub, j.JobID+"-"+safeName(filename)))
	dst := filepath.Join(s.loreDir, filepath.FromSlash(rel))
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return nil, err
	}
	if err := os.WriteFile(dst, data, 0o644); err != nil {
		return nil, err
	}
	j.Staged = rel
	raw, _ := json.MarshalIndent(j, "", "  ")
	if err := os.WriteFile(filepath.Join(s.jobsDir(), j.JobID+".json"), raw, 0o644); err != nil {
		return nil, err
	}
	_ = s.Reload()
	return &store.Receipt{JobID: j.JobID, State: j.State, Message: fmt.Sprintf("%s staged at .lore/%s and %s", filename, rel, queuedNote)}, nil
}

func (s *FileStore) UpdatePersona(ctx context.Context, req store.PersonaRequest) (*store.Receipt, error) {
	if strings.TrimSpace(req.Content) == "" || req.Filename == "" {
		return nil, errors.New("content and filename are both required, e.g. filename backend.md")
	}
	if int64(len(req.Content)) > int64(s.cfg.MaxUploadMB)<<20 {
		return nil, fmt.Errorf("content is larger than %d MB", s.cfg.MaxUploadMB)
	}
	return s.stageUpload("personas", req.Filename, []byte(req.Content), "draft", "persona_update")
}

func (s *FileStore) LogDecision(ctx context.Context, req store.LogDecisionRequest) (*store.Receipt, error) {
	if strings.TrimSpace(req.Outcome) == "" {
		return nil, errors.New("outcome is required, e.g. \"implemented refresh endpoint following rule:auth/refresh-rotation@v2\"")
	}
	sn := s.current()
	var unknown []string
	for _, id := range req.RuleIDs {
		if sn.byID[id] == nil {
			unknown = append(unknown, id)
		}
	}
	if len(unknown) > 0 {
		return nil, fmt.Errorf("unknown rule ids: %s; cite ids exactly as returned by get_context", strings.Join(unknown, ", "))
	}
	o := lineage.Outcome{Outcome: req.Outcome, Note: req.Note, RuleIDs: req.RuleIDs, At: s.now().Format(time.RFC3339)}
	if req.DecisionID != "" {
		if err := s.rec.AppendOutcome(req.DecisionID, o); err != nil {
			return nil, err
		}
		return &store.Receipt{DecisionID: req.DecisionID, State: "recorded", Message: "Outcome attached to " + req.DecisionID + "."}, nil
	}
	if strings.TrimSpace(req.Task) == "" {
		return nil, errors.New("pass decision_id from a get_context result, or task describing what was decided")
	}
	rec := &lineage.Record{
		Tool: "log_decision", Task: &result.Task{Intent: req.Task}, Verdict: result.OK, Directive: result.DirectiveFor(result.OK),
		Constants: s.constants(), GraphSnapshot: sn.hash, ConfidenceMode: "deterministic",
		CreatedAt: o.At, Outcomes: []lineage.Outcome{o}, Summary: req.Task,
	}
	for i, id := range req.RuleIDs {
		rec.Used = append(rec.Used, lineage.UsedRef{ID: id, Rank: i + 1})
	}
	id, err := s.rec.Write(rec)
	if err != nil {
		return nil, err
	}
	return &store.Receipt{DecisionID: id, State: "recorded", Message: "Decision " + id + " recorded."}, nil
}
