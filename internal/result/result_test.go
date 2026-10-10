package result

import (
	"encoding/json"
	"testing"
)

func TestDirectiveFor(t *testing.T) {
	cases := map[Verdict]Directive{
		OK:          ProceedAndCite,
		OKWithNotes: ProceedAndCite,
		Conflict:    AskUser,
		Abstain:     AskUser,
		Violation:   Stop,
		Denied:      Stop,
		NoKnowledge: Proceed,
	}
	for v, want := range cases {
		if got := DirectiveFor(v); got != want {
			t.Errorf("DirectiveFor(%s) = %s, want %s", v, got, want)
		}
	}
}

func TestStronger(t *testing.T) {
	if !Stronger(Conflict, OK) || Stronger(OK, Conflict) || !Stronger(Denied, Violation) {
		t.Fatal("verdict precedence is wrong")
	}
}

func sample() *Envelope {
	e := New("get_context")
	e.DecisionID = "dec-0142"
	e.SetVerdict(Conflict)
	e.Summary = "2 rules apply to src/auth/token.go; 1 conflict must be resolved."
	e.Task = &Task{File: "src/auth/token.go", Intent: "add refresh-token endpoint"}
	e.Items = append(e.Items, Item{
		ID: "rule:auth/jwt-expiry@v3", Kind: KindRule, Modality: "must", Role: RoleApplies,
		Authority: "policy", Status: "stable", Freshness: FreshCurrent, Origin: "human_authored",
		Confidence: Confidence{Band: BandHigh, P: 0.93},
		Text:       "Access tokens expire in 15 minutes or less.",
		Source:     Source{Path: "policies/auth.md", Anchor: "L42", EffectiveFrom: "2026-07-01"},
	})
	e.Conflicts = append(e.Conflicts, ConflictSummary{
		ID: "conf-0031", Left: "rule:auth/refresh-rotation@v2", Right: "rule:auth/refresh-static@v1",
		Kind: "partial", Severity: "high", Status: "open", Owner: "@security",
	})
	e.Excluded = Excluded{Superseded: 1, Draft: 2}
	e.Budget = Budget{Limit: 800, Used: 312}
	e.Links = []string{"lore://rules/auth/jwt-expiry@v3", "lore://decisions/dec-0142"}
	e.AsOf = "2026-09-29T10:40:00+06:00"
	e.Constants = Constants{AbstainBand: [2]float64{0.45, 0.55}, ConflictMinConf: 0.7, TokenBudget: 800, ConfidenceMode: "deterministic"}
	return e
}

func TestSampleValidates(t *testing.T) {
	if err := Validate(sample()); err != nil {
		t.Fatalf("sample envelope invalid: %v", err)
	}
}

func TestSchemaRejectsBadEnvelopes(t *testing.T) {
	bad := map[string]func(*Envelope){
		"unknown verdict":   func(e *Envelope) { e.Verdict = "maybe" },
		"raw uuid id":       func(e *Envelope) { e.Items[0].ID = "3f2c1a9e-0000-4000-8000-000000000000" },
		"non-lore link":     func(e *Envelope) { e.Links = []string{"https://example.com"} },
		"draft in context":  func(e *Envelope) { e.Items[0].Status = "draft" },
		"bad decision id":   func(e *Envelope) { e.DecisionID = "decision-1" },
		"confidence over 1": func(e *Envelope) { e.Items[0].Confidence.P = 1.5 },
	}
	for name, mutate := range bad {
		e := sample()
		mutate(e)
		if err := Validate(e); err == nil {
			t.Errorf("%s: expected schema error", name)
		}
	}
}

func TestEmptyCollectionsSerialize(t *testing.T) {
	raw, _ := json.Marshal(New("stats"))
	var m map[string]any
	_ = json.Unmarshal(raw, &m)
	for _, k := range []string{"items", "conflicts", "links"} {
		if _, ok := m[k].([]any); !ok {
			t.Errorf("%s should serialize as an empty array, got %v", k, m[k])
		}
	}
}
