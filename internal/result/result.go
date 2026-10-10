// Package result defines the lore.result/1 envelope shared by every read surface.
package result

import "encoding/json"

const SchemaID = "lore.result/1"

type Verdict string

const (
	Denied      Verdict = "denied"
	Violation   Verdict = "violation"
	Conflict    Verdict = "conflict"
	Abstain     Verdict = "abstain"
	OKWithNotes Verdict = "ok_with_notes"
	OK          Verdict = "ok"
	NoKnowledge Verdict = "no_knowledge"
)

// Precedence lists verdicts from strongest to weakest.
var Precedence = []Verdict{Denied, Violation, Conflict, Abstain, OKWithNotes, OK, NoKnowledge}

// Stronger reports whether a outranks b.
func Stronger(a, b Verdict) bool { return rank(a) < rank(b) }

func rank(v Verdict) int {
	for i, p := range Precedence {
		if p == v {
			return i
		}
	}
	return len(Precedence)
}

type Directive string

const (
	Proceed        Directive = "proceed"
	ProceedAndCite Directive = "proceed_and_cite"
	AskUser        Directive = "ask_user"
	Stop           Directive = "stop"
)

// DirectiveFor maps a verdict to its directive (FR-PRS-04).
func DirectiveFor(v Verdict) Directive {
	switch v {
	case OK, OKWithNotes:
		return ProceedAndCite
	case Conflict, Abstain:
		return AskUser
	case Violation, Denied:
		return Stop
	default:
		return Proceed
	}
}

// Item kinds. Chunk is only returned by search, for unreviewed text.
const (
	KindRule      = "rule"
	KindSkill     = "skill"
	KindProcedure = "procedure"
	KindChunk     = "chunk"
)

const (
	RoleApplies    = "applies"
	RoleConstrains = "constrains"
	RoleExempts    = "exempts"
	RoleBackground = "background"
)

const (
	FreshCurrent = "current"
	FreshAging   = "aging"
)

const (
	BandHigh   = "high"
	BandMedium = "medium"
)

// Excluded reasons.
const (
	ReasonSuperseded    = "superseded"
	ReasonDraft         = "draft"
	ReasonQuarantine    = "quarantine"
	ReasonOutOfScope    = "out_of_scope"
	ReasonStale         = "stale"
	ReasonLowConfidence = "low_confidence"
	ReasonDenied        = "denied"
)

type Envelope struct {
	Schema     string            `json:"schema"`
	DecisionID string            `json:"decision_id,omitempty"`
	Tool       string            `json:"tool"`
	Verdict    Verdict           `json:"verdict"`
	Directive  Directive         `json:"directive"`
	Summary    string            `json:"summary"`
	Task       *Task             `json:"task,omitempty"`
	Items      []Item            `json:"items"`
	Conflicts  []ConflictSummary `json:"conflicts"`
	Violations []RuleViolation   `json:"violations,omitempty"`
	Excluded   Excluded          `json:"excluded"`
	Budget     Budget            `json:"budget"`
	Links      []string          `json:"links"`
	Data       map[string]any    `json:"data,omitempty"`
	AsOf       string            `json:"as_of"`
	Constants  Constants         `json:"constants"`
}

type Task struct {
	File    string `json:"file,omitempty" yaml:"file,omitempty"`
	Intent  string `json:"intent,omitempty" yaml:"intent,omitempty"`
	DiffRef string `json:"diff_ref,omitempty" yaml:"diff_ref,omitempty"`
}

type Item struct {
	ID         string     `json:"id"`
	Kind       string     `json:"kind"`
	Modality   string     `json:"modality,omitempty"`
	Role       string     `json:"role"`
	Authority  string     `json:"authority"`
	Status     string     `json:"status"`
	Freshness  string     `json:"freshness"`
	Origin     string     `json:"origin"`
	Confidence Confidence `json:"confidence"`
	Title      string     `json:"title,omitempty"`
	Text       string     `json:"text"`
	Source     Source     `json:"source"`
}

type Confidence struct {
	Band string  `json:"band"`
	P    float64 `json:"p"`
}

type Source struct {
	Path          string `json:"path"`
	Anchor        string `json:"anchor"`
	EffectiveFrom string `json:"effective_from,omitempty"`
	LastVerified  string `json:"last_verified,omitempty"`
}

type ConflictSummary struct {
	ID           string `json:"id"`
	Left         string `json:"left"`
	Right        string `json:"right"`
	Kind         string `json:"kind"`
	Severity     string `json:"severity"`
	ScopeOverlap string `json:"scope_overlap,omitempty"`
	Status       string `json:"status"`
	Owner        string `json:"owner,omitempty"`
}

type RuleViolation struct {
	RuleID   string   `json:"rule_id"`
	Severity string   `json:"severity"`
	Evidence []string `json:"evidence"`
	P        float64  `json:"p"`
}

type Excluded struct {
	Superseded    int `json:"superseded"`
	Draft         int `json:"draft"`
	Quarantine    int `json:"quarantine"`
	OutOfScope    int `json:"out_of_scope"`
	Stale         int `json:"stale"`
	LowConfidence int `json:"low_confidence"`
	Denied        int `json:"denied"`
}

// Add increments the counter for reason.
func (e *Excluded) Add(reason string) {
	switch reason {
	case ReasonSuperseded:
		e.Superseded++
	case ReasonDraft:
		e.Draft++
	case ReasonQuarantine:
		e.Quarantine++
	case ReasonOutOfScope:
		e.OutOfScope++
	case ReasonStale:
		e.Stale++
	case ReasonLowConfidence:
		e.LowConfidence++
	case ReasonDenied:
		e.Denied++
	}
}

func (e Excluded) Total() int {
	return e.Superseded + e.Draft + e.Quarantine + e.OutOfScope + e.Stale + e.LowConfidence + e.Denied
}

type Budget struct {
	Limit int `json:"limit"`
	Used  int `json:"used"`
}

// Constants records the thresholds in effect so a decision can be reproduced.
type Constants struct {
	AbstainBand     [2]float64 `json:"abstain_band" yaml:"abstain_band"`
	ConflictMinConf float64    `json:"conflict_min_conf" yaml:"conflict_min_conf"`
	TokenBudget     int        `json:"token_budget" yaml:"token_budget"`
	// ConfidenceMode is "deterministic" until the Jev checker is wired in.
	ConfidenceMode string `json:"confidence_mode" yaml:"confidence_mode"`
}

// New returns an envelope with required collections initialised.
func New(tool string) *Envelope {
	return &Envelope{
		Schema:    SchemaID,
		Tool:      tool,
		Items:     []Item{},
		Conflicts: []ConflictSummary{},
		Links:     []string{},
	}
}

// MarshalJSON emits required collections as [] even when they are nil.
func (e Envelope) MarshalJSON() ([]byte, error) {
	type plain Envelope
	if e.Items == nil {
		e.Items = []Item{}
	}
	if e.Conflicts == nil {
		e.Conflicts = []ConflictSummary{}
	}
	if e.Links == nil {
		e.Links = []string{}
	}
	return json.Marshal(plain(e))
}

// SetVerdict sets the verdict and its directive together.
func (e *Envelope) SetVerdict(v Verdict) {
	e.Verdict = v
	e.Directive = DirectiveFor(v)
}
