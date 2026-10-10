// Package review holds human-only governance actions. Nothing here is reachable from MCP.
package review

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"

	"github.com/DJRCX/lore/internal/okf"
)

// Promote marks a draft rule, skill or procedure as stable so it can reach live context.
func Promote(loreDir, id string) error {
	dir, rest, ok := okf.DirForID(id)
	if !ok || (dir != "rules" && dir != "skills" && dir != "procedures") {
		return fmt.Errorf("%q is not a rule, skill or procedure id", id)
	}
	path := filepath.Join(loreDir, dir, filepath.FromSlash(rest)+".md")
	data, err := os.ReadFile(path)
	if errors.Is(err, fs.ErrNotExist) {
		return fmt.Errorf("%s not found (looked for %s)", id, path)
	}
	if err != nil {
		return err
	}
	d, err := okf.Parse(filepath.Join(dir, rest+".md"), data)
	if err != nil {
		return err
	}
	if d.Front.Status == "stable" {
		return fmt.Errorf("%s is already stable", id)
	}
	if d.Front.Status == "deprecated" {
		return fmt.Errorf("%s is deprecated; create a new version instead", id)
	}
	if err := okf.SetField(path, "status", "stable"); err != nil {
		return err
	}
	if d.Front.Authority == "draft" || d.Front.Authority == "" {
		if err := okf.SetField(path, "authority", "reviewed"); err != nil {
			return err
		}
	}
	if d.Front.Origin == "llm_extracted" {
		if err := okf.SetField(path, "origin", "llm_extracted_reviewed"); err != nil {
			return err
		}
	}
	return nil
}
