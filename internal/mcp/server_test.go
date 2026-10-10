package mcp

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
	"github.com/DJRCX/lore/internal/result"
	"github.com/DJRCX/lore/internal/store/filestore"
	"github.com/modelcontextprotocol/go-sdk/mcp"
)

func connect(t *testing.T) (*mcp.ClientSession, string) {
	t.Helper()
	root := t.TempDir()
	loreDir := filepath.Join(root, config.LoreDir)
	if err := demo.WriteTo(loreDir, false); err != nil {
		t.Fatal(err)
	}
	st, err := filestore.Open(root, config.Default(), filestore.Options{
		Now: func() time.Time { return time.Date(2026, 10, 5, 12, 0, 0, 0, time.UTC) },
	})
	if err != nil {
		t.Fatal(err)
	}
	srv := New(st, Options{Version: "test", LoreDir: loreDir})
	ctx := context.Background()
	ct, stt := mcp.NewInMemoryTransports()
	ss, err := srv.MCP().Connect(ctx, stt, nil)
	if err != nil {
		t.Fatal(err)
	}
	cs, err := mcp.NewClient(&mcp.Implementation{Name: "test-client", Version: "0"}, nil).Connect(ctx, ct, nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		cs.Close()
		ss.Wait()
		st.Close()
	})
	return cs, loreDir
}

func callTool(t *testing.T, cs *mcp.ClientSession, name string, args map[string]any) *mcp.CallToolResult {
	t.Helper()
	res, err := cs.CallTool(context.Background(), &mcp.CallToolParams{Name: name, Arguments: args})
	if err != nil {
		t.Fatalf("%s: %v", name, err)
	}
	return res
}

func envelope(t *testing.T, res *mcp.CallToolResult) *result.Envelope {
	t.Helper()
	if res.IsError {
		t.Fatalf("tool error: %s", textOf(res))
	}
	raw, err := json.Marshal(res.StructuredContent)
	if err != nil {
		t.Fatal(err)
	}
	if err := result.ValidateJSON(raw); err != nil {
		t.Fatalf("structuredContent invalid: %v\n%s", err, raw)
	}
	var env result.Envelope
	if err := json.Unmarshal(raw, &env); err != nil {
		t.Fatal(err)
	}
	return &env
}

func textOf(res *mcp.CallToolResult) string {
	for _, c := range res.Content {
		if tc, ok := c.(*mcp.TextContent); ok {
			return tc.Text
		}
	}
	return ""
}

func TestInitializeAndLists(t *testing.T) {
	cs, _ := connect(t)
	ctx := context.Background()
	if !strings.Contains(cs.InitializeResult().Instructions, "get_context") {
		t.Error("instructions not sent")
	}

	tools, err := cs.ListTools(ctx, nil)
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]bool{"get_context": true, "check_compliance": true, "detect_conflicts": true, "get_skill": true, "search": true,
		"get_history": true, "trace": true, "stats": true, "ingest_status": true, "ingest": false, "update_persona": false, "log_decision": false}
	got := map[string]*mcp.Tool{}
	for _, tl := range tools.Tools {
		got[tl.Name] = tl
	}
	for name, ro := range want {
		tl := got[name]
		if tl == nil {
			t.Errorf("tool %s missing", name)
			continue
		}
		if tl.Annotations == nil || tl.Annotations.ReadOnlyHint != ro {
			t.Errorf("%s readOnlyHint = %v, want %v", name, tl.Annotations, ro)
		}
		if ro && tl.OutputSchema == nil {
			t.Errorf("%s has no output schema", name)
		}
	}
	if len(got) != len(want) {
		t.Errorf("got %d tools, want %d", len(got), len(want))
	}
	raw, _ := json.Marshal(tools.Tools)
	if strings.Contains(string(raw), `"type":[`) {
		t.Error("a tool schema uses a type array, which single-type clients such as Gemini reject")
	}
	for _, forbidden := range []string{"promote", "resolve_conflict", "approve"} {
		if got[forbidden] != nil {
			t.Errorf("%s must not be exposed over MCP", forbidden)
		}
	}

	res, err := cs.ListResources(ctx, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(res.Resources) < 5 {
		t.Errorf("only %d resources", len(res.Resources))
	}
	tpls, err := cs.ListResourceTemplates(ctx, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(tpls.ResourceTemplates) != len(templates) {
		t.Errorf("templates = %d", len(tpls.ResourceTemplates))
	}
	prompts, err := cs.ListPrompts(ctx, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(prompts.Prompts) != 4 {
		t.Errorf("prompts = %d", len(prompts.Prompts))
	}
}

func TestGetContextDemo(t *testing.T) {
	cs, loreDir := connect(t)
	res := callTool(t, cs, "get_context", map[string]any{"file_path": "src/auth/token.go", "intent": "add a refresh token endpoint"})
	env := envelope(t, res)
	if env.Verdict != result.Conflict || env.Directive != result.AskUser {
		t.Fatalf("verdict = %s/%s", env.Verdict, env.Directive)
	}
	if len(env.Conflicts) != 1 || env.Conflicts[0].ID != "conf-0031" {
		t.Errorf("conflicts = %+v", env.Conflicts)
	}
	for _, it := range env.Items {
		if it.ID == "rule:auth/jwt-expiry@v2" || it.ID == "rule:auth/session-cookie@v1" {
			t.Errorf("%s must not be served", it.ID)
		}
	}
	text := textOf(res)
	if !strings.HasPrefix(text, `<lore verdict="conflict" directive="ask_user"`) || !strings.Contains(text, "do not resolve yourself") {
		t.Errorf("agent text:\n%s", text)
	}
	links := 0
	for _, c := range res.Content {
		if _, ok := c.(*mcp.ResourceLink); ok {
			links++
		}
	}
	if links == 0 {
		t.Error("no resource links")
	}
	if _, err := os.Stat(filepath.Join(loreDir, "decisions", env.DecisionID+".md")); err != nil {
		t.Errorf("decision file: %v", err)
	}
	audit, _ := os.ReadFile(filepath.Join(loreDir, "audit.log"))
	if !strings.Contains(string(audit), `"tool":"get_context"`) || !strings.Contains(string(audit), env.DecisionID) {
		t.Errorf("audit log = %s", audit)
	}

	rd, err := cs.ReadResource(context.Background(), &mcp.ReadResourceParams{URI: "lore://decisions/" + env.DecisionID})
	if err != nil || !strings.Contains(rd.Contents[0].Text, "conf-0031") {
		t.Errorf("decision resource = %v %v", rd, err)
	}
	tr := envelope(t, callTool(t, cs, "trace", map[string]any{"decision_id": env.DecisionID}))
	if tr.Data["prov_graph"] == nil {
		t.Error("trace has no prov_graph")
	}
}

func TestEveryReadToolValidates(t *testing.T) {
	cs, _ := connect(t)
	calls := map[string]map[string]any{
		"check_compliance": {"diff": "--- a/src/auth/token.go\n+++ b/src/auth/token.go\n@@\n+log.Println(tok)\n"},
		"detect_conflicts": {},
		"get_skill":        {"name": "error-wrapping"},
		"search":           {"query": "token", "include_unverified": true},
		"get_history":      {"file_path": "src/auth/token.go"},
		"stats":            {},
		"ingest_status":    {},
	}
	for name, args := range calls {
		env := envelope(t, callTool(t, cs, name, args))
		if env.Tool == "" || env.Verdict == "" {
			t.Errorf("%s: empty envelope", name)
		}
	}
}

func TestErrorsAreToolErrorsWithHints(t *testing.T) {
	cs, _ := connect(t)
	res := callTool(t, cs, "get_context", map[string]any{"file_path": "src/a.go", "response_format": "verbose"})
	if !res.IsError || !strings.Contains(textOf(res), "concise or detailed") {
		t.Errorf("bad response_format: %v %q", res.IsError, textOf(res))
	}
	res = callTool(t, cs, "trace", map[string]any{"decision_id": "../../etc/passwd"})
	if !res.IsError {
		t.Error("path traversal in decision_id accepted")
	}
	if _, err := cs.ReadResource(context.Background(), &mcp.ReadResourceParams{URI: "lore://rules/nope@v1"}); err == nil {
		t.Error("unknown resource returned no error")
	}
}

func TestWriteIdempotency(t *testing.T) {
	cs, loreDir := connect(t)
	args := map[string]any{"content": "# Auth\nRotate keys yearly.", "filename": "keys.md", "idempotency_key": "abc"}
	first := callTool(t, cs, "ingest", args)
	second := callTool(t, cs, "ingest", args)
	if first.IsError || second.IsError {
		t.Fatalf("ingest errors: %s / %s", textOf(first), textOf(second))
	}
	if !strings.Contains(textOf(second), "Already done") {
		t.Errorf("replay not reported: %s", textOf(second))
	}
	jobs, _ := os.ReadDir(filepath.Join(loreDir, "_staging", "jobs"))
	if len(jobs) != 1 {
		t.Errorf("%d jobs written, want 1", len(jobs))
	}

	env := envelope(t, callTool(t, cs, "get_context", map[string]any{"file_path": "src/auth/token.go"}))
	res := callTool(t, cs, "log_decision", map[string]any{"decision_id": env.DecisionID, "outcome": "asked the user", "rule_ids": []string{"rule:auth/jwt-expiry@v3"}})
	if res.IsError {
		t.Errorf("log_decision: %s", textOf(res))
	}
}

func TestPrompts(t *testing.T) {
	cs, _ := connect(t)
	ctx := context.Background()
	p, err := cs.GetPrompt(ctx, &mcp.GetPromptParams{Name: "explain_conflict", Arguments: map[string]string{"scope": "component:auth"}})
	if err != nil {
		t.Fatal(err)
	}
	if txt := p.Messages[0].Content.(*mcp.TextContent).Text; !strings.Contains(txt, "conf-0031") || !strings.Contains(txt, "Do not recommend") {
		t.Errorf("explain_conflict = %s", txt)
	}
	for _, name := range []string{"validate_change", "prepare_review_packet"} {
		if _, err := cs.GetPrompt(ctx, &mcp.GetPromptParams{Name: name}); err != nil {
			t.Errorf("%s: %v", name, err)
		}
	}
	if _, err := cs.GetPrompt(ctx, &mcp.GetPromptParams{Name: "answer_with_lore", Arguments: map[string]string{"question": "how long do tokens live?"}}); err != nil {
		t.Error(err)
	}
}
