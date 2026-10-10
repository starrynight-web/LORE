package lineage

import (
	"strings"
	"sync"
	"testing"

	"github.com/starrynight-web/LORE/internal/result"
)

func TestWriteGetAppend(t *testing.T) {
	r := NewRecorder(t.TempDir())
	id, err := r.Write(&Record{Tool: "get_context", Verdict: result.Conflict, Directive: result.AskUser,
		Used: []UsedRef{{ID: "rule:a@v1", Rank: 1}}, Excluded: []ExcludedRef{{ID: "rule:a@v0", Reason: "superseded"}}})
	if err != nil {
		t.Fatal(err)
	}
	if id != "dec-0001" {
		t.Fatalf("first id = %s", id)
	}
	if err := r.AppendOutcome(id, Outcome{Outcome: "asked user", RuleIDs: []string{"rule:a@v1"}}); err != nil {
		t.Fatal(err)
	}
	rec, err := r.Get(id)
	if err != nil {
		t.Fatal(err)
	}
	if rec.Verdict != result.Conflict || len(rec.Used) != 1 || len(rec.Outcomes) != 1 {
		t.Fatalf("unexpected record %+v", rec)
	}
	if _, err := r.Get("../etc/passwd"); err == nil {
		t.Fatal("path traversal accepted")
	}
}

func TestRecordKeysMatchSchema(t *testing.T) {
	r := NewRecorder(t.TempDir())
	id, err := r.Write(&Record{Tool: "check_compliance", Verdict: result.Abstain,
		Task:      &result.Task{File: "a.go", DiffRef: "sha256:abc"},
		Constants: result.Constants{AbstainBand: [2]float64{0.45, 0.55}, ConflictMinConf: 0.7, TokenBudget: 800, ConfidenceMode: "deterministic"}})
	if err != nil {
		t.Fatal(err)
	}
	raw, err := r.Raw(id)
	if err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{"diff_ref:", "abstain_band:", "conflict_min_conf:", "token_budget:"} {
		if !strings.Contains(string(raw), key) {
			t.Errorf("missing %s in:\n%s", key, raw)
		}
	}
	rec, err := r.Get(id)
	if err != nil || rec.Constants.TokenBudget != 800 || rec.Task.DiffRef != "sha256:abc" {
		t.Errorf("round trip = %+v, %v", rec, err)
	}
}

func TestConcurrentIDsAreUnique(t *testing.T) {
	r := NewRecorder(t.TempDir())
	var wg sync.WaitGroup
	ids := make(chan string, 20)
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			id, err := r.Write(&Record{Tool: "get_context", Verdict: result.OK})
			if err != nil {
				t.Error(err)
			}
			ids <- id
		}()
	}
	wg.Wait()
	close(ids)
	seen := map[string]bool{}
	for id := range ids {
		if seen[id] {
			t.Fatalf("duplicate id %s", id)
		}
		seen[id] = true
	}
}
