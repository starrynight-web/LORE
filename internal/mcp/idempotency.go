package mcp

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/starrynight-web/LORE/internal/store"
)

const idemTTL = 24 * time.Hour

type idemEntry struct {
	Tool    string        `json:"tool"`
	At      time.Time     `json:"at"`
	Receipt store.Receipt `json:"receipt"`
}

// idempotency remembers write receipts by (tool, idempotency_key) so a retried
// call returns the first receipt instead of writing twice.
type idempotency struct {
	mu   sync.Mutex
	path string
}

func newIdempotency(loreDir string) *idempotency {
	return &idempotency{path: filepath.Join(loreDir, "_staging", "idempotency.json")}
}

func (i *idempotency) load() map[string]idemEntry {
	m := map[string]idemEntry{}
	data, err := os.ReadFile(i.path)
	if err == nil {
		_ = json.Unmarshal(data, &m)
	}
	return m
}

// do returns the stored receipt for key, or runs fn and stores its receipt.
func (i *idempotency) do(tool, key string, fn func() (*store.Receipt, error)) (*store.Receipt, bool, error) {
	if i == nil || key == "" {
		r, err := fn()
		return r, false, err
	}
	i.mu.Lock()
	defer i.mu.Unlock()
	m := i.load()
	k := tool + "|" + key
	if e, ok := m[k]; ok && time.Since(e.At) < idemTTL {
		r := e.Receipt
		return &r, true, nil
	}
	r, err := fn()
	if err != nil {
		return nil, false, err
	}
	now := time.Now()
	for key, e := range m {
		if now.Sub(e.At) >= idemTTL {
			delete(m, key)
		}
	}
	m[k] = idemEntry{Tool: tool, At: now, Receipt: *r}
	if data, err := json.MarshalIndent(m, "", "  "); err == nil {
		_ = os.MkdirAll(filepath.Dir(i.path), 0o755)
		_ = os.WriteFile(i.path, data, 0o644)
	}
	return r, false, nil
}
