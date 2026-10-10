package skills

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/starrynight-web/LORE/internal/okf"
	"github.com/starrynight-web/LORE/internal/review"
)

var now = func() time.Time { return time.Date(2026, 10, 5, 0, 0, 0, 0, time.UTC) }

func copyTree(t *testing.T, src, dst string) {
	t.Helper()
	err := filepath.WalkDir(src, func(p string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(src, p)
		if d.IsDir() {
			return os.MkdirAll(filepath.Join(dst, rel), 0o755)
		}
		data, err := os.ReadFile(p)
		if err != nil {
			return err
		}
		return os.WriteFile(filepath.Join(dst, rel), data, 0o644)
	})
	if err != nil {
		t.Fatal(err)
	}
}

func byName(rs []Result) map[string]Result {
	m := map[string]Result{}
	for _, r := range rs {
		m[r.Name+"|"+r.Action] = r
	}
	return m
}

func TestImport(t *testing.T) {
	lore := filepath.Join(t.TempDir(), ".lore")
	src := filepath.Join(t.TempDir(), "skills")
	copyTree(t, "testdata/skills", src)
	if err := os.Symlink(filepath.Join(src, "http-retries"), filepath.Join(src, "retries-link")); err != nil {
		t.Fatal(err)
	}

	rs, err := Import(lore, []string{src}, Options{Now: now})
	if err != nil {
		t.Fatal(err)
	}
	m := byName(rs)
	if len(rs) != 3 {
		t.Fatalf("results = %+v", rs)
	}
	if _, ok := m["http-retries|imported"]; !ok {
		t.Errorf("http-retries not imported: %+v", rs)
	}
	if _, ok := m["commit-messages|imported"]; !ok {
		t.Errorf("commit-messages not imported: %+v", rs)
	}
	dups := 0
	for _, r := range rs {
		if r.Action == "duplicate" {
			dups++
		}
	}
	if dups != 1 {
		t.Errorf("want 1 duplicate (symlink), got %d: %+v", dups, rs)
	}

	data, err := os.ReadFile(filepath.Join(lore, "skills", "http-retries@v1.md"))
	if err != nil {
		t.Fatal(err)
	}
	d, err := okf.Parse("skills/http-retries@v1.md", data)
	if err != nil {
		t.Fatal(err)
	}
	if d.Front.Status != "draft" || d.Front.SourceID != "src:skill-http-retries@v1" {
		t.Errorf("entry front = %+v", d.Front)
	}
	if d.Front.Description != "Retry idempotent HTTP calls with capped exponential backoff and jitter." {
		t.Errorf("description = %q", d.Front.Description)
	}
	if !strings.Contains(d.Body, "Backoff") {
		t.Errorf("body lacks section index: %q", d.Body)
	}
	if _, err := os.Stat(filepath.Join(lore, "_staging", "skills", "http-retries@v1", "reference.md")); err != nil {
		t.Errorf("reference file not staged: %v", err)
	}
	if _, err := os.Stat(filepath.Join(lore, "components", "global.md")); err != nil {
		t.Errorf("global component missing: %v", err)
	}

	cm, _ := os.ReadFile(filepath.Join(lore, "skills", "commit-messages@v1.md"))
	if !strings.Contains(string(cm), "imperative mood") {
		t.Errorf("description not taken from first paragraph:\n%s", cm)
	}

	// Re-import without changes is a no-op.
	rs, _ = Import(lore, []string{filepath.Join(src, "http-retries")}, Options{Now: now})
	if rs[0].Action != "unchanged" {
		t.Errorf("re-import = %+v", rs[0])
	}

	// A content change creates v2 superseding v1.
	if err := os.WriteFile(filepath.Join(src, "http-retries", "reference.md"), []byte("# Status codes\n\n- 429: retry after Retry-After.\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	rs, _ = Import(lore, []string{filepath.Join(src, "http-retries")}, Options{Now: now})
	if rs[0].Action != "updated" || rs[0].ID != "skill:http-retries@v2" {
		t.Fatalf("update = %+v", rs[0])
	}
	v2, _ := os.ReadFile(filepath.Join(lore, "skills", "http-retries@v2.md"))
	if !strings.Contains(string(v2), "supersedes: skill:http-retries@v1") {
		t.Errorf("v2 does not supersede v1:\n%s", v2)
	}

	if err := review.Promote(lore, "skill:http-retries@v2"); err != nil {
		t.Fatal(err)
	}
	if err := review.Promote(lore, "skill:http-retries@v2"); err == nil {
		t.Error("promoting a stable item twice should fail")
	}
}

func TestImportRejectsBadAuthority(t *testing.T) {
	if _, err := Import(t.TempDir(), []string{"testdata/skills"}, Options{Authority: "root"}); err == nil {
		t.Error("bad authority accepted")
	}
}

func TestFindSkipsFoldersWithoutSkill(t *testing.T) {
	rs, err := Import(filepath.Join(t.TempDir(), ".lore"), []string{t.TempDir()}, Options{Now: now})
	if err != nil {
		t.Fatal(err)
	}
	if len(rs) != 1 || rs[0].Action != "skipped" {
		t.Errorf("results = %+v", rs)
	}
}
