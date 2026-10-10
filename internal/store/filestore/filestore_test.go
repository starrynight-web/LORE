package filestore

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/DJRCX/lore/internal/config"
	"github.com/DJRCX/lore/internal/demo"
	"github.com/DJRCX/lore/internal/importer/skills"
	"github.com/DJRCX/lore/internal/present"
	"github.com/DJRCX/lore/internal/result"
	"github.com/DJRCX/lore/internal/review"
	"github.com/DJRCX/lore/internal/store"
)

var fixedNow = func() time.Time { return time.Date(2026, 10, 5, 12, 0, 0, 0, time.UTC) }

func openDemo(t *testing.T) *FileStore {
	t.Helper()
	root := t.TempDir()
	if err := demo.WriteTo(filepath.Join(root, config.LoreDir), false); err != nil {
		t.Fatal(err)
	}
	s, err := Open(root, config.Default(), Options{Now: fixedNow})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { s.Close() })
	return s
}

func mustValid(t *testing.T, env *result.Envelope) {
	t.Helper()
	raw, err := json.Marshal(env)
	if err != nil {
		t.Fatal(err)
	}
	if err := result.ValidateJSON(raw); err != nil {
		t.Fatalf("envelope fails lore.result/1: %v\n%s", err, raw)
	}
}

func ids(env *result.Envelope) []string {
	var out []string
	for _, it := range env.Items {
		out = append(out, it.ID)
	}
	return out
}

func has(list []string, v string) bool {
	for _, x := range list {
		if x == v {
			return true
		}
	}
	return false
}

func TestDemoContext(t *testing.T) {
	s := openDemo(t)
	env, err := s.Context(context.Background(), store.ContextRequest{FilePath: "src/auth/token.go", Intent: "add a refresh token endpoint"})
	if err != nil {
		t.Fatal(err)
	}
	mustValid(t, env)
	t.Log(present.AgentText(env, false))

	if env.Verdict != result.Conflict || env.Directive != result.AskUser {
		t.Fatalf("verdict = %s/%s, want conflict/ask_user", env.Verdict, env.Directive)
	}
	got := ids(env)
	for _, want := range []string{"rule:auth/jwt-expiry@v3", "rule:auth/no-token-logging@v1", "rule:auth/refresh-rotation@v2", "rule:auth/refresh-static@v1", "skill:go/error-wrapping@v2"} {
		if !has(got, want) {
			t.Errorf("missing %s in %v", want, got)
		}
	}
	for _, banned := range []string{"rule:auth/jwt-expiry@v2", "rule:auth/session-cookie@v1", "rule:api/rate-limit@v1", "rule:auth/password-hash@v1"} {
		if has(got, banned) {
			t.Errorf("%s should be excluded", banned)
		}
	}
	if len(env.Conflicts) != 1 || env.Conflicts[0].ID != "conf-0031" {
		t.Errorf("conflicts = %+v", env.Conflicts)
	}
	if env.Excluded.Superseded < 1 || env.Excluded.Draft < 1 {
		t.Errorf("excluded = %+v", env.Excluded)
	}
	if env.Budget.Used > env.Budget.Limit {
		t.Errorf("budget %d > %d", env.Budget.Used, env.Budget.Limit)
	}
	if env.DecisionID == "" {
		t.Fatal("no decision id")
	}

	tr, err := s.Trace(context.Background(), env.DecisionID)
	if err != nil {
		t.Fatal(err)
	}
	mustValid(t, tr)
	if tr.Verdict != result.OK || tr.Data["prov_graph"] == nil {
		t.Errorf("trace = %s %v", tr.Verdict, tr.Data)
	}
}

func TestDryRunWritesNothing(t *testing.T) {
	s := openDemo(t)
	env, err := s.Context(context.Background(), store.ContextRequest{FilePath: "src/auth/token.go", DryRun: true})
	if err != nil {
		t.Fatal(err)
	}
	if env.DecisionID != "" {
		t.Errorf("dry run produced %s", env.DecisionID)
	}
	if n := len(s.rec.List()); n != 0 {
		t.Errorf("%d decisions written", n)
	}
}

func TestNoKnowledge(t *testing.T) {
	s := openDemo(t)
	env, err := s.Context(context.Background(), store.ContextRequest{FilePath: "docs/readme.md", Intent: "fix typo"})
	if err != nil {
		t.Fatal(err)
	}
	mustValid(t, env)
	if env.Verdict != result.NoKnowledge || env.Directive != result.Proceed {
		t.Errorf("verdict = %s/%s", env.Verdict, env.Directive)
	}
}

func TestComplianceAbstainsWithoutChecker(t *testing.T) {
	s := openDemo(t)
	diff := "--- a/src/api/users.go\n+++ b/src/api/users.go\n@@\n+log.Printf(\"token=%s\", tok)\n"
	env, err := s.Compliance(context.Background(), store.ComplianceRequest{Diff: diff})
	if err != nil {
		t.Fatal(err)
	}
	mustValid(t, env)
	if env.Verdict != result.Abstain {
		t.Errorf("verdict = %s, want abstain", env.Verdict)
	}
	if !has(ids(env), "rule:auth/no-token-logging@v1") {
		t.Errorf("items = %v", ids(env))
	}
}

func TestComplianceWithoutDiffChecksFile(t *testing.T) {
	s := openDemo(t)
	ctx := context.Background()
	if err := os.MkdirAll(filepath.Join(s.Root(), "src", "api"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(s.Root(), "src", "api", "users.go"), []byte("package api\n\nfunc logToken(tok string) { println(tok) }\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	env, err := s.Compliance(ctx, store.ComplianceRequest{FilePath: "src/api/users.go", DryRun: true})
	if err != nil {
		t.Fatal(err)
	}
	mustValid(t, env)
	if env.Verdict != result.Abstain || !strings.HasPrefix(env.Task.DiffRef, "file:sha256:") || !strings.Contains(env.Summary, "the file as it is now") {
		t.Errorf("file check = %s %q %q", env.Verdict, env.Task.DiffRef, env.Summary)
	}
	if !has(ids(env), "rule:auth/no-token-logging@v1") {
		t.Errorf("items = %v", ids(env))
	}
	for _, bad := range []store.ComplianceRequest{{}, {FilePath: "../outside.go"}, {FilePath: "/etc/passwd"}, {FilePath: "src/missing.go"}} {
		if _, err := s.Compliance(ctx, bad); err == nil {
			t.Errorf("%+v accepted", bad)
		}
	}
}

func TestReads(t *testing.T) {
	s := openDemo(t)
	ctx := context.Background()

	c, err := s.Conflicts(ctx, store.ConflictsRequest{Scope: "src/auth/token.go"})
	if err != nil {
		t.Fatal(err)
	}
	mustValid(t, c)
	if c.Verdict != result.Conflict || len(c.Conflicts) != 1 {
		t.Errorf("conflicts = %s %+v", c.Verdict, c.Conflicts)
	}

	sk, err := s.Skill(ctx, "error-wrapping")
	if err != nil {
		t.Fatal(err)
	}
	mustValid(t, sk)
	if sk.Verdict != result.OK || !has(ids(sk), "skill:go/error-wrapping@v2") {
		t.Errorf("skill = %s %v", sk.Verdict, ids(sk))
	}

	se, err := s.Search(ctx, store.SearchRequest{Query: "jwt expiry"})
	if err != nil {
		t.Fatal(err)
	}
	mustValid(t, se)
	if len(se.Items) == 0 || se.Items[0].ID != "rule:auth/jwt-expiry@v3" {
		t.Errorf("search = %v", ids(se))
	}

	h, err := s.History(ctx, store.HistoryRequest{ItemID: "rule:auth/jwt-expiry@v3"})
	if err != nil {
		t.Fatal(err)
	}
	mustValid(t, h)

	st, err := s.Stats(ctx)
	if err != nil {
		t.Fatal(err)
	}
	mustValid(t, st)
	if errs := st.Data["stats"].(map[string]any)["load_errors"]; errs != nil && len(errs.([]string)) > 0 {
		t.Errorf("demo bundle has load errors: %v", errs)
	}
}

func TestResources(t *testing.T) {
	s := openDemo(t)
	ctx := context.Background()
	list, err := s.ListResources(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if len(list) < 5 {
		t.Fatalf("only %d resources", len(list))
	}
	for _, uri := range []string{"lore://rules/auth/jwt-expiry@v3", "lore://conflicts/conf-0031", "lore://schemas/lore.result.v1"} {
		r, err := s.ReadResource(ctx, uri)
		if err != nil || r.Text == "" {
			t.Errorf("%s: %v", uri, err)
		}
	}
	for _, bad := range []string{"lore://rules/../lore.config", "lore://sources/policies-auth-md/../../lore.config.yaml", "file:///etc/passwd"} {
		if _, err := s.ReadResource(ctx, bad); err == nil {
			t.Errorf("%s should be rejected", bad)
		}
	}
}

func TestWrites(t *testing.T) {
	s := openDemo(t)
	ctx := context.Background()

	rc, err := s.Ingest(ctx, store.IngestRequest{Content: "# Policy\nNever log tokens.", Filename: "../evil name.md"})
	if err != nil {
		t.Fatal(err)
	}
	if rc.State != "queued" || rc.JobID != "job-0001" {
		t.Errorf("receipt = %+v", rc)
	}
	if _, err := os.Stat(filepath.Join(s.LoreDir(), "_staging", "uploads", "job-0001-evil-name.md")); err != nil {
		t.Errorf("upload not staged safely: %v", err)
	}
	st, err := s.IngestStatus(ctx, "job-0001")
	if err != nil || st.Verdict != result.OK {
		t.Errorf("status = %v %v", st, err)
	}
	if _, err := s.Ingest(ctx, store.IngestRequest{Content: "x", Filename: "a.md", Authority: "god"}); err == nil {
		t.Error("bad authority accepted")
	}

	env, _ := s.Context(ctx, store.ContextRequest{FilePath: "src/auth/token.go"})
	if _, err := s.LogDecision(ctx, store.LogDecisionRequest{DecisionID: env.DecisionID, Outcome: "asked user", RuleIDs: []string{"rule:auth/jwt-expiry@v3"}}); err != nil {
		t.Fatal(err)
	}
	if _, err := s.LogDecision(ctx, store.LogDecisionRequest{Task: "x", Outcome: "y", RuleIDs: []string{"rule:nope@v1"}}); err == nil {
		t.Error("unknown rule accepted")
	}
	rc, err = s.LogDecision(ctx, store.LogDecisionRequest{Task: "chose rotation", Outcome: "done"})
	if err != nil || !strings.HasPrefix(rc.DecisionID, "dec-") {
		t.Errorf("log decision = %+v %v", rc, err)
	}
}

func writeSkill(t *testing.T, dir, name, body string) string {
	t.Helper()
	p := filepath.Join(dir, name)
	if err := os.MkdirAll(p, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(p, "SKILL.md"), []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	return p
}

func TestImportedSkillLifecycle(t *testing.T) {
	s := openDemo(t)
	ctx := context.Background()
	src := t.TempDir()
	writeSkill(t, src, "sql-migrations", "---\nname: sql-migrations\ndescription: Write reversible SQL migrations. Always add a down step.\n---\n# SQL migrations\n\n## Reversible steps\nEvery migration needs a down step that restores the schema.\n\n## Locking\nAvoid long table locks on large tables; backfill in batches.\n")

	rc, err := s.Ingest(ctx, store.IngestRequest{Path: src})
	if err != nil {
		t.Fatal(err)
	}
	if len(rc.ItemIDs) != 1 || rc.ItemIDs[0] != "skill:sql-migrations@v1" {
		t.Fatalf("receipt = %+v", rc)
	}

	sk, _ := s.Skill(ctx, "sql-migrations")
	if sk.Verdict != result.NoKnowledge {
		t.Errorf("draft skill served: %s", sk.Verdict)
	}
	se, _ := s.Search(ctx, store.SearchRequest{Query: "table locks backfill", IncludeUnverified: true})
	found := false
	for _, it := range se.Items {
		if it.Kind == result.KindChunk && strings.Contains(it.ID, "skill-sql-migrations@v1") {
			found = true
		}
	}
	if !found {
		t.Errorf("staged skill text not searchable as unverified: %v", ids(se))
	}

	if err := review.Promote(s.LoreDir(), "skill:sql-migrations@v1"); err != nil {
		t.Fatal(err)
	}
	if err := s.Reload(); err != nil {
		t.Fatal(err)
	}
	sk, _ = s.Skill(ctx, "sql-migrations")
	mustValid(t, sk)
	if sk.Verdict != result.OK || sk.Data["sections"] == nil {
		t.Errorf("promoted skill = %s data=%v", sk.Verdict, sk.Data)
	}
	r, err := s.ReadResource(ctx, "lore://skills/sql-migrations@v1")
	if err != nil || !strings.Contains(r.Text, "Avoid long table locks") {
		t.Errorf("skill resource = %v %v", r, err)
	}

	// Global skills only reach get_context with a keyword hit.
	env, _ := s.Context(ctx, store.ContextRequest{FilePath: "db/migrate/0001.sql", Intent: "add a reversible migration", DryRun: true})
	if !has(ids(env), "skill:sql-migrations@v1") {
		t.Errorf("keyword-matched global skill missing: %v", ids(env))
	}
	env, _ = s.Context(ctx, store.ContextRequest{FilePath: "internal/util/strings.go", Intent: "rename variable", DryRun: true})
	if has(ids(env), "skill:sql-migrations@v1") {
		t.Errorf("global skill served without keyword match: %v", ids(env))
	}
	if _, err := os.Stat(filepath.Join(s.LoreDir(), "components", "global.md")); err != nil {
		t.Errorf("%s component not created: %v", skills.GlobalComponent, err)
	}
}
