// Package lineage writes and reads Decision records (.lore/decisions/dec-NNNN.md).
package lineage

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/starrynight-web/LORE/internal/okf"
	"github.com/starrynight-web/LORE/internal/result"
	"gopkg.in/yaml.v3"
)

type UsedRef struct {
	ID   string `yaml:"id" json:"id"`
	Rank int    `yaml:"rank" json:"rank"`
}

type ExcludedRef struct {
	ID     string `yaml:"id" json:"id"`
	Reason string `yaml:"reason" json:"reason"`
}

type Outcome struct {
	At      string   `yaml:"at" json:"at"`
	Outcome string   `yaml:"outcome" json:"outcome"`
	Note    string   `yaml:"note,omitempty" json:"note,omitempty"`
	RuleIDs []string `yaml:"rule_ids,omitempty" json:"rule_ids,omitempty"`
}

// Record is DR-05.
type Record struct {
	Type           string           `yaml:"type" json:"-"`
	DecisionID     string           `yaml:"decision_id" json:"decision_id"`
	Tool           string           `yaml:"tool" json:"tool"`
	Task           *result.Task     `yaml:"task,omitempty" json:"task,omitempty"`
	File           string           `yaml:"file,omitempty" json:"file,omitempty"`
	Verdict        result.Verdict   `yaml:"verdict" json:"verdict"`
	Directive      result.Directive `yaml:"directive" json:"directive"`
	Used           []UsedRef        `yaml:"used" json:"used"`
	Excluded       []ExcludedRef    `yaml:"excluded" json:"excluded"`
	Conflicts      []string         `yaml:"conflicts,omitempty" json:"conflicts,omitempty"`
	Constants      result.Constants `yaml:"constants" json:"constants"`
	GraphSnapshot  string           `yaml:"graph_snapshot" json:"graph_snapshot"`
	ConfidenceMode string           `yaml:"confidence_mode" json:"confidence_mode"`
	CreatedAt      string           `yaml:"created_at" json:"created_at"`
	Outcomes       []Outcome        `yaml:"outcomes,omitempty" json:"outcomes,omitempty"`
	Summary        string           `yaml:"-" json:"summary,omitempty"`
}

// Recorder allocates decision IDs and persists records. It is safe across
// goroutines and across processes sharing the same directory (IDs are claimed
// with O_EXCL).
type Recorder struct {
	dir string
	mu  sync.Mutex
}

func NewRecorder(loreDir string) *Recorder {
	return &Recorder{dir: filepath.Join(loreDir, "decisions")}
}

var idRe = regexp.MustCompile(`^dec-(\d+)\.md$`)

func (r *Recorder) maxID() int {
	entries, _ := os.ReadDir(r.dir)
	max := 0
	for _, e := range entries {
		if m := idRe.FindStringSubmatch(e.Name()); m != nil {
			if n, _ := strconv.Atoi(m[1]); n > max {
				max = n
			}
		}
	}
	return max
}

// Write assigns the next decision ID, stores the record and returns the ID.
func (r *Recorder) Write(rec *Record) (string, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if err := os.MkdirAll(r.dir, 0o755); err != nil {
		return "", err
	}
	rec.Type = "decision"
	if rec.CreatedAt == "" {
		rec.CreatedAt = time.Now().Format(time.RFC3339)
	}
	for attempt := 0; attempt < 50; attempt++ {
		id := fmt.Sprintf("dec-%04d", r.maxID()+1)
		f, err := os.OpenFile(filepath.Join(r.dir, id+".md"), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o644)
		if errors.Is(err, fs.ErrExist) {
			continue
		}
		if err != nil {
			return "", err
		}
		rec.DecisionID = id
		data, err := okf.Marshal(rec, body(rec))
		if err == nil {
			_, err = f.Write(data)
		}
		if cerr := f.Close(); err == nil {
			err = cerr
		}
		return id, err
	}
	return "", errors.New("could not allocate a decision id")
}

func body(rec *Record) string {
	if rec.Summary == "" {
		return ""
	}
	return rec.Summary + "\n"
}

// Get loads one decision record.
func (r *Recorder) Get(id string) (*Record, error) {
	if !idRe.MatchString(id + ".md") {
		return nil, fmt.Errorf("%q is not a decision id (expected dec-NNNN)", id)
	}
	data, err := os.ReadFile(filepath.Join(r.dir, id+".md"))
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return nil, fmt.Errorf("decision %s not found", id)
		}
		return nil, err
	}
	fm, b, _, err := okf.Split(data)
	if err != nil {
		return nil, err
	}
	var rec Record
	if err := yaml.Unmarshal(fm, &rec); err != nil {
		return nil, err
	}
	rec.Summary = strings.TrimSpace(b)
	return &rec, nil
}

// Raw returns the decision file as stored.
func (r *Recorder) Raw(id string) ([]byte, error) {
	if !idRe.MatchString(id + ".md") {
		return nil, fmt.Errorf("%q is not a decision id", id)
	}
	return os.ReadFile(filepath.Join(r.dir, id+".md"))
}

// AppendOutcome attaches an outcome reported by an agent (log_decision).
func (r *Recorder) AppendOutcome(id string, o Outcome) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	rec, err := r.Get(id)
	if err != nil {
		return err
	}
	if o.At == "" {
		o.At = time.Now().Format(time.RFC3339)
	}
	rec.Outcomes = append(rec.Outcomes, o)
	rec.Type = "decision"
	data, err := okf.Marshal(rec, body(rec))
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(r.dir, id+".md"), data, 0o644)
}

// List returns decision IDs, newest first.
func (r *Recorder) List() []string {
	entries, _ := os.ReadDir(r.dir)
	var ids []string
	for _, e := range entries {
		if idRe.MatchString(e.Name()) {
			ids = append(ids, strings.TrimSuffix(e.Name(), ".md"))
		}
	}
	sort.Sort(sort.Reverse(sort.StringSlice(ids)))
	return ids
}
