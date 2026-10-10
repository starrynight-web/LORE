package mcp

import (
	"context"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/DJRCX/lore/internal/present"
	"github.com/DJRCX/lore/internal/result"
	"github.com/DJRCX/lore/internal/store"
	"github.com/DJRCX/lore/schemas"
	"github.com/google/jsonschema-go/jsonschema"
	"github.com/modelcontextprotocol/go-sdk/mcp"
)

type ContextIn struct {
	FilePath       string `json:"file_path" jsonschema:"Repo-relative path of the file you are about to create or edit, e.g. src/auth/token.go"`
	Intent         string `json:"intent,omitempty" jsonschema:"One line describing the change, e.g. add a refresh-token endpoint"`
	AsOf           string `json:"as_of,omitempty" jsonschema:"Evaluate as of this date (YYYY-MM-DD); omit for today"`
	ResponseFormat string `json:"response_format,omitempty" jsonschema:"concise (default) or detailed (adds anchors, probabilities and follow-up IDs)"`
}

type ComplianceIn struct {
	Diff           string `json:"diff,omitempty" jsonschema:"Unified diff of the change to check (e.g. git diff). Omit it to check file_path as it is now."`
	FilePath       string `json:"file_path,omitempty" jsonschema:"Repo-relative path of the changed file. Required when there is no diff, e.g. outside a git repository."`
	ResponseFormat string `json:"response_format,omitempty" jsonschema:"concise (default) or detailed"`
}

type ConflictsIn struct {
	Scope  string `json:"scope,omitempty" jsonschema:"A component ID such as component:auth, or a repo-relative file path; omit for everything"`
	Status string `json:"status,omitempty" jsonschema:"open (default) or all"`
}

type SkillIn struct {
	Name string `json:"name" jsonschema:"Skill name such as error-wrapping, or a full ID such as skill:go/error-wrapping@v2"`
}

type SearchIn struct {
	Query             string `json:"query" jsonschema:"Words to search for in rule, skill and procedure text"`
	Component         string `json:"component,omitempty" jsonschema:"Restrict to one component ID, e.g. component:auth"`
	IncludeUnverified bool   `json:"include_unverified,omitempty" jsonschema:"Also search unreviewed source text (returned with the Unverified badge)"`
	Limit             int    `json:"limit,omitempty" jsonschema:"Maximum results (default and maximum 20)"`
}

type HistoryIn struct {
	FilePath string `json:"file_path,omitempty" jsonschema:"Repo-relative file path whose rules' version history you want"`
	ItemID   string `json:"item_id,omitempty" jsonschema:"An item ID such as rule:auth/jwt-expiry@v3"`
}

type TraceIn struct {
	DecisionID string `json:"decision_id" jsonschema:"Decision ID returned by get_context or check_compliance, e.g. dec-0042"`
}

type StatsIn struct{}

type IngestStatusIn struct {
	JobID string `json:"job_id,omitempty" jsonschema:"Job ID returned by ingest; omit to list all jobs"`
}

type IngestIn struct {
	Path           string `json:"path,omitempty" jsonschema:"File or skill folder to ingest, repo-relative or absolute. A folder containing SKILL.md is imported as a draft skill."`
	Content        string `json:"content,omitempty" jsonschema:"Document text to ingest when there is no file on disk"`
	Filename       string `json:"filename,omitempty" jsonschema:"Name for content, e.g. auth-policy.md (required with content)"`
	Authority      string `json:"authority,omitempty" jsonschema:"Claimed authority: policy, team_convention, procedure, reviewed or draft (default). A person confirms it on review."`
	IdempotencyKey string `json:"idempotency_key,omitempty" jsonschema:"Any unique string; repeating it returns the first receipt instead of ingesting twice"`
}

type PersonaIn struct {
	Content        string `json:"content" jsonschema:"Persona or team profile text in markdown"`
	Filename       string `json:"filename" jsonschema:"Name such as backend-team.md"`
	IdempotencyKey string `json:"idempotency_key,omitempty" jsonschema:"Any unique string; repeating it returns the first receipt"`
}

type LogDecisionIn struct {
	DecisionID     string   `json:"decision_id,omitempty" jsonschema:"Decision ID from get_context to attach the outcome to"`
	Task           string   `json:"task,omitempty" jsonschema:"What was decided, when there is no decision_id"`
	RuleIDs        []string `json:"rule_ids,omitempty" jsonschema:"Rule IDs you followed, exactly as returned by Lore"`
	Outcome        string   `json:"outcome" jsonschema:"One line: what you did, or what the user chose"`
	Note           string   `json:"note,omitempty" jsonschema:"Optional detail, e.g. the user's reason"`
	IdempotencyKey string   `json:"idempotency_key,omitempty" jsonschema:"Any unique string; repeating it returns the first receipt"`
}

func detailed(format string) (bool, error) {
	switch format {
	case "", "concise":
		return false, nil
	case "detailed":
		return true, nil
	}
	return false, fmt.Errorf("response_format %q is not supported; use concise or detailed", format)
}

// schemaFor infers T's JSON Schema with nullable types such as ["null","array"]
// collapsed to the single non-null type, which single-type dialects (e.g. Gemini
// function declarations) require.
func schemaFor[T any]() *jsonschema.Schema {
	s, err := jsonschema.For[T](nil)
	if err != nil {
		panic(fmt.Sprintf("schema for %T: %v", *new(T), err))
	}
	collapseNullable(s)
	return s
}

func collapseNullable(s *jsonschema.Schema) {
	if s == nil {
		return
	}
	if len(s.Types) == 2 && slices.Contains(s.Types, "null") {
		for _, t := range s.Types {
			if t != "null" {
				s.Type, s.Types = t, nil
			}
		}
	}
	collapseNullable(s.Items)
	for _, p := range s.Properties {
		collapseNullable(p)
	}
}

func readOnly(title string) *mcp.ToolAnnotations {
	return &mcp.ToolAnnotations{Title: title, ReadOnlyHint: true, OpenWorldHint: new(false)}
}

// readTool registers a tool returning a lore.result/1 envelope.
func readTool[In any](s *Server, name, title, desc string, ann *mcp.ToolAnnotations, fn func(context.Context, In) (*result.Envelope, bool, error)) {
	tool := &mcp.Tool{Name: name, Title: title, Description: desc, Annotations: ann, InputSchema: schemaFor[In](), OutputSchema: schemas.ResultV1Map()}
	mcp.AddTool(s.srv, tool, func(ctx context.Context, _ *mcp.CallToolRequest, in In) (*mcp.CallToolResult, *result.Envelope, error) {
		start := time.Now()
		var det bool
		env, err := call(ctx, s.opts.Timeout, func(ctx context.Context) (*result.Envelope, error) {
			e, d, err := fn(ctx, in)
			det = d
			return e, err
		})
		ev := auditEvent{Tool: name, ArgsHash: argsHash(in), DurationMS: time.Since(start).Milliseconds()}
		if err != nil {
			ev.Error = err.Error()
			s.audit.write(ev)
			return nil, nil, err
		}
		ev.Verdict, ev.DecisionID = string(env.Verdict), env.DecisionID
		s.audit.write(ev)
		return &mcp.CallToolResult{Content: content(env, det)}, env, nil
	})
}

func content(env *result.Envelope, det bool) []mcp.Content {
	out := []mcp.Content{&mcp.TextContent{Text: present.AgentText(env, det)}}
	const maxLinks = 10
	for i, l := range env.Links {
		if i == maxLinks {
			break
		}
		out = append(out, &mcp.ResourceLink{URI: l, Name: strings.TrimPrefix(l, "lore://"), MIMEType: "text/markdown"})
	}
	return out
}

func (s *Server) addReadTools() {
	st := s.st
	readTool(s, "get_context", "Get governed context for a file",
		"Call before creating or editing a file. Returns the rules, skills and procedures that apply to file_path for this intent, any recorded conflicts between them, a verdict and a directive (proceed, proceed_and_cite, ask_user, stop) you must follow. Records a decision_id for log_decision and trace.",
		readOnly("Get governed context"),
		func(ctx context.Context, in ContextIn) (*result.Envelope, bool, error) {
			det, err := detailed(in.ResponseFormat)
			if err != nil {
				return nil, false, err
			}
			if strings.TrimSpace(in.FilePath) == "" {
				return nil, false, fmt.Errorf("file_path is required, e.g. src/auth/token.go")
			}
			env, err := st.Context(ctx, store.ContextRequest{FilePath: in.FilePath, Intent: in.Intent, AsOf: in.AsOf, Detailed: det})
			return env, det, err
		})
	readTool(s, "check_compliance", "Check a diff against MUST rules",
		"Call before finishing a change, with its unified diff, or with just file_path when there is no diff (e.g. no git repository). Returns the MUST and MUST NOT rules that apply. Without the Jev checker the verdict is abstain: review the change against each rule yourself and tell the user which ones you checked.",
		readOnly("Check compliance"),
		func(ctx context.Context, in ComplianceIn) (*result.Envelope, bool, error) {
			det, err := detailed(in.ResponseFormat)
			if err != nil {
				return nil, false, err
			}
			env, err := st.Compliance(ctx, store.ComplianceRequest{Diff: in.Diff, FilePath: in.FilePath, Detailed: det})
			return env, det, err
		})
	readTool(s, "detect_conflicts", "List recorded conflicts",
		"Lists recorded conflicts between rules, optionally for one component or file. Conflicts are resolved by people; present both sides and never pick one yourself.",
		readOnly("Detect conflicts"),
		func(ctx context.Context, in ConflictsIn) (*result.Envelope, bool, error) {
			env, err := st.Conflicts(ctx, store.ConflictsRequest{Scope: in.Scope, Status: in.Status})
			return env, false, err
		})
	readTool(s, "get_skill", "Get a skill",
		"Returns one approved skill with its section index. Read the lore://skills/ link for the full text, or a section anchor for part of it.",
		readOnly("Get skill"),
		func(ctx context.Context, in SkillIn) (*result.Envelope, bool, error) {
			env, err := st.Skill(ctx, in.Name)
			return env, false, err
		})
	readTool(s, "search", "Search knowledge",
		"Keyword search over approved rules, skills and procedures. Set include_unverified to also search unreviewed source text; those results are hints, never rules.",
		readOnly("Search"),
		func(ctx context.Context, in SearchIn) (*result.Envelope, bool, error) {
			env, err := st.Search(ctx, store.SearchRequest{Query: in.Query, Component: in.Component, IncludeUnverified: in.IncludeUnverified, Limit: in.Limit})
			return env, false, err
		})
	readTool(s, "get_history", "Get version history",
		"Shows how the rules for a file, or one item, changed over time: every version, which one is live, and why the others are not.",
		readOnly("Get history"),
		func(ctx context.Context, in HistoryIn) (*result.Envelope, bool, error) {
			env, err := st.History(ctx, store.HistoryRequest{FilePath: in.FilePath, ItemID: in.ItemID})
			return env, false, err
		})
	readTool(s, "trace", "Trace a decision",
		"Explains a past decision: which items were used or excluded and why, their sources and owners, as a provenance graph.",
		readOnly("Trace decision"),
		func(ctx context.Context, in TraceIn) (*result.Envelope, bool, error) {
			env, err := st.Trace(ctx, in.DecisionID)
			return env, false, err
		})
	readTool(s, "stats", "Knowledge stats",
		"Counts of live items, drafts awaiting review, open conflicts, unverified chunks and ingest jobs.",
		readOnly("Stats"),
		func(ctx context.Context, _ StatsIn) (*result.Envelope, bool, error) {
			env, err := st.Stats(ctx)
			return env, false, err
		})
	readTool(s, "ingest_status", "Ingest job status",
		"Shows the state of ingest jobs created by ingest or update_persona.",
		readOnly("Ingest status"),
		func(ctx context.Context, in IngestStatusIn) (*result.Envelope, bool, error) {
			env, err := st.IngestStatus(ctx, in.JobID)
			return env, false, err
		})
}

// writeTool registers a tool returning a store.Receipt, deduplicated by idempotency_key.
func writeTool[In any](s *Server, name, title, desc string, key func(In) string, fn func(context.Context, In) (*store.Receipt, error)) {
	tool := &mcp.Tool{Name: name, Title: title, Description: desc, InputSchema: schemaFor[In](), OutputSchema: schemaFor[store.Receipt](), Annotations: &mcp.ToolAnnotations{
		Title: title, DestructiveHint: new(false), IdempotentHint: true, OpenWorldHint: new(false),
	}}
	mcp.AddTool(s.srv, tool, func(ctx context.Context, _ *mcp.CallToolRequest, in In) (*mcp.CallToolResult, *store.Receipt, error) {
		start := time.Now()
		var replay bool
		rc, err := call(ctx, s.opts.Timeout, func(ctx context.Context) (*store.Receipt, error) {
			r, rep, err := s.idem.do(name, key(in), func() (*store.Receipt, error) { return fn(ctx, in) })
			replay = rep
			return r, err
		})
		ev := auditEvent{Tool: name, ArgsHash: argsHash(in), DurationMS: time.Since(start).Milliseconds()}
		if err != nil {
			ev.Error = err.Error()
			s.audit.write(ev)
			return nil, nil, err
		}
		ev.DecisionID, ev.JobID = rc.DecisionID, rc.JobID
		s.audit.write(ev)
		msg := rc.Message
		if replay {
			msg = "Already done for this idempotency_key; returning the first receipt. " + msg
		}
		return &mcp.CallToolResult{Content: []mcp.Content{&mcp.TextContent{Text: msg}}}, rc, nil
	})
}

func (s *Server) addWriteTools() {
	st := s.st
	writeTool(s, "ingest", "Ingest a document or skill",
		"Stages a document (path, or content plus filename) for review. A folder containing SKILL.md is imported as a draft skill. Nothing ingested here reaches get_context until a person approves it.",
		func(in IngestIn) string { return in.IdempotencyKey },
		func(ctx context.Context, in IngestIn) (*store.Receipt, error) {
			return st.Ingest(ctx, store.IngestRequest{Path: in.Path, Content: in.Content, Filename: in.Filename, Authority: in.Authority})
		})
	writeTool(s, "update_persona", "Propose a persona update",
		"Stages a persona or team profile document as a draft for review.",
		func(in PersonaIn) string { return in.IdempotencyKey },
		func(ctx context.Context, in PersonaIn) (*store.Receipt, error) {
			return st.UpdatePersona(ctx, store.PersonaRequest{Content: in.Content, Filename: in.Filename})
		})
	writeTool(s, "log_decision", "Record a decision outcome",
		"Records what you did after get_context: pass its decision_id, the rule IDs you followed and a one-line outcome (including the user's choice when a conflict was raised).",
		func(in LogDecisionIn) string { return in.IdempotencyKey },
		func(ctx context.Context, in LogDecisionIn) (*store.Receipt, error) {
			return st.LogDecision(ctx, store.LogDecisionRequest{DecisionID: in.DecisionID, Task: in.Task, RuleIDs: in.RuleIDs, Outcome: in.Outcome, Note: in.Note})
		})
}
