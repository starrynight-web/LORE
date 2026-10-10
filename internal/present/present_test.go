package present

import (
	"strings"
	"testing"

	"github.com/starrynight-web/LORE/internal/result"
)

func conflictEnv() *result.Envelope {
	e := result.New("get_context")
	e.SetVerdict(result.Conflict)
	e.DecisionID = "dec-0007"
	e.AsOf = "2026-10-05T00:00:00Z"
	e.Summary = "2 rules apply; 1 conflict must be resolved."
	e.Task = &result.Task{File: "src/auth/token.go", Intent: "add refresh"}
	item := func(id, mod, text string) result.Item {
		return result.Item{ID: id, Kind: result.KindRule, Modality: mod, Role: result.RoleApplies, Authority: "policy",
			Status: "stable", Freshness: result.FreshCurrent, Confidence: result.Confidence{Band: result.BandHigh, P: 0.9}, Text: text}
	}
	e.Items = []result.Item{
		item("rule:a@v1", "must", "Do A."),
		item("rule:b@v1", "must", "Do B."),
		item("rule:c@v1", "must_not", "Never C."),
	}
	e.Conflicts = []result.ConflictSummary{{ID: "conf-0001", Left: "rule:a@v1", Right: "rule:b@v1", Kind: "direct", Severity: "high", Status: "open"}}
	e.Excluded.Add(result.ReasonSuperseded)
	return e
}

func TestAgentTextShape(t *testing.T) {
	out := AgentText(conflictEnv(), false)
	for _, want := range []string{
		`<lore verdict="conflict" directive="ask_user" decision="dec-0007"`,
		"CONFLICT — do not resolve yourself",
		"[rule:c@v1] Never C.",
		"Not applied: 1 superseded",
		"Next:",
		"</lore>",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("missing %q in:\n%s", want, out)
		}
	}
	mustSection := out[strings.Index(out, "MUST"):strings.Index(out, "CONFLICT")]
	if strings.Contains(mustSection, "rule:a@v1") {
		t.Errorf("conflict side listed as a plain MUST:\n%s", out)
	}
}

func TestCLITextMentionsTrace(t *testing.T) {
	if out := CLIText(conflictEnv()); !strings.Contains(out, "lore trace dec-0007") {
		t.Errorf("CLI text:\n%s", out)
	}
}
