package filestore

import (
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/DJRCX/lore/internal/chunk"
	"github.com/DJRCX/lore/internal/okf"
	"github.com/DJRCX/lore/internal/text"
)

const chunkChars = 1600

// chunkRec is an unreviewed section of a staged file. Chunks are derived on
// load, used only by search, and never reach get_context or check_compliance.
type chunkRec struct {
	ID       string
	SourceID string
	File     string // path inside the staged folder, or the staged path for uploads
	Display  string // path shown to users
	Anchor   string
	Heading  string
	Text     string
	strong   map[string]bool
	weak     map[string]bool
}

var chunkExt = map[string]bool{".md": true, ".markdown": true, ".txt": true, ".mdx": true}

func buildChunks(loreDir string, sources map[string]*okf.Doc) []chunkRec {
	staging := filepath.Join(loreDir, "_staging")
	byStaged := map[string]*okf.Doc{}
	for _, src := range sources {
		if src.Front.Staged != "" {
			byStaged[filepath.ToSlash(src.Front.Staged)] = src
		}
	}
	var out []chunkRec
	_ = filepath.WalkDir(staging, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		rel, _ := filepath.Rel(loreDir, p)
		rel = filepath.ToSlash(rel)
		if d.IsDir() {
			if rel == "_staging/jobs" {
				return filepath.SkipDir
			}
			return nil
		}
		if !chunkExt[strings.ToLower(filepath.Ext(p))] {
			return nil
		}
		data, err := os.ReadFile(p)
		if err != nil {
			return nil
		}
		srcID, key, file, display := "", "upload", rel, rel
		for staged, src := range byStaged {
			if strings.HasPrefix(rel, staged+"/") {
				srcID = src.ID
				key = strings.TrimPrefix(src.ID, "src:")
				file = strings.TrimPrefix(rel, staged+"/")
				display = strings.TrimSuffix(src.Front.Path, "/") + "/" + file
				break
			}
		}
		for _, sec := range chunk.Split(string(data), chunkChars) {
			if strings.TrimSpace(sec.Text) == "" {
				continue
			}
			anchor := fmt.Sprintf("%s#L%d", filepath.Base(file), sec.Line)
			out = append(out, chunkRec{
				ID:       fmt.Sprintf("chunk:%s/%s#L%d", key, file, sec.Line),
				SourceID: srcID, File: file, Display: display, Anchor: anchor,
				Heading: sec.Heading, Text: sec.Text,
				strong: text.Set(text.Terms(sec.Heading)),
				weak:   text.Set(text.Terms(sec.Text)),
			})
		}
		return nil
	})
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out
}

func (c *chunkRec) relevance(q []string) int {
	score := 0
	for _, t := range q {
		switch {
		case c.strong[t]:
			score += 2
		case c.weak[t]:
			score++
		}
	}
	return score
}
