package mcp

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
	"time"
)

type auditEvent struct {
	TS         string `json:"ts"`
	Tool       string `json:"tool"`
	ArgsHash   string `json:"args_sha256"`
	Verdict    string `json:"verdict,omitempty"`
	DecisionID string `json:"decision_id,omitempty"`
	JobID      string `json:"job_id,omitempty"`
	DurationMS int64  `json:"duration_ms"`
	Error      string `json:"error,omitempty"`
}

type auditLog struct {
	mu   sync.Mutex
	path string
}

func newAuditLog(loreDir string) *auditLog {
	return &auditLog{path: filepath.Join(loreDir, "audit.log")}
}

func argsHash(args any) string {
	raw, _ := json.Marshal(args)
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])[:16]
}

func (a *auditLog) write(e auditEvent) {
	if a == nil {
		return
	}
	e.TS = time.Now().UTC().Format(time.RFC3339)
	line, err := json.Marshal(e)
	if err != nil {
		return
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	f, err := os.OpenFile(a.path, os.O_WRONLY|os.O_CREATE|os.O_APPEND, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	_, _ = f.Write(append(line, '\n'))
}
