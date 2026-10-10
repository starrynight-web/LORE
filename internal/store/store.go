// Package store defines the engine contract the MCP server (and later the HTTP
// API and CLI) depend on. The file-backed implementation lives in filestore;
// a Neo4j + Jev implementation will satisfy the same interface.
package store

import (
	"context"

	"github.com/starrynight-web/LORE/internal/result"
)

type ContextRequest struct {
	FilePath string
	Intent   string
	Detailed bool
	AsOf     string // YYYY-MM-DD; empty means today
	DryRun   bool   // skip writing a decision record
}

type ComplianceRequest struct {
	Diff     string
	FilePath string
	Detailed bool
	DryRun   bool
}

type ConflictsRequest struct {
	Scope  string // component ID or file path; empty means everything
	Status string // open (default) | all
}

type SearchRequest struct {
	Query             string
	Component         string
	IncludeUnverified bool
	Limit             int
}

type HistoryRequest struct {
	FilePath string
	ItemID   string
}

type IngestRequest struct {
	Path      string
	Content   string
	Filename  string
	Authority string
}

type PersonaRequest struct {
	Content  string
	Filename string
}

type LogDecisionRequest struct {
	DecisionID string
	Task       string
	RuleIDs    []string
	Outcome    string
	Note       string
}

// Receipt is returned by write operations.
type Receipt struct {
	JobID      string   `json:"job_id,omitempty"`
	DecisionID string   `json:"decision_id,omitempty"`
	State      string   `json:"state"`
	Message    string   `json:"message"`
	ItemIDs    []string `json:"item_ids,omitempty"`
}

// Resource is a readable lore:// document.
type Resource struct {
	URI         string
	Name        string
	Title       string
	Description string
	MIMEType    string
	Text        string
}

type Store interface {
	Context(ctx context.Context, req ContextRequest) (*result.Envelope, error)
	Compliance(ctx context.Context, req ComplianceRequest) (*result.Envelope, error)
	Conflicts(ctx context.Context, req ConflictsRequest) (*result.Envelope, error)
	Skill(ctx context.Context, name string) (*result.Envelope, error)
	Search(ctx context.Context, req SearchRequest) (*result.Envelope, error)
	History(ctx context.Context, req HistoryRequest) (*result.Envelope, error)
	Trace(ctx context.Context, decisionID string) (*result.Envelope, error)
	Stats(ctx context.Context) (*result.Envelope, error)
	IngestStatus(ctx context.Context, jobID string) (*result.Envelope, error)

	Ingest(ctx context.Context, req IngestRequest) (*Receipt, error)
	UpdatePersona(ctx context.Context, req PersonaRequest) (*Receipt, error)
	LogDecision(ctx context.Context, req LogDecisionRequest) (*Receipt, error)

	ListResources(ctx context.Context) ([]Resource, error)
	ReadResource(ctx context.Context, uri string) (*Resource, error)

	// OnChange registers a callback fired after the knowledge set reloads.
	OnChange(func())
	Close() error
}

// ErrNotFound marks lookups of unknown IDs or URIs.
type ErrNotFound struct{ What string }

func (e ErrNotFound) Error() string { return e.What + " not found" }
