// Package demo embeds the starter OKF bundle used by `lore init --demo`,
// the tests, and the IDE smoke-test project.
package demo

import (
	"embed"
	"io/fs"
	"os"
	"path/filepath"
)

//go:embed all:bundle
var bundle embed.FS

// FS returns the bundle rooted at its .lore directory.
func FS() fs.FS {
	sub, err := fs.Sub(bundle, "bundle/.lore")
	if err != nil {
		panic(err)
	}
	return sub
}

// WriteTo copies the demo bundle into loreDir. Existing files are kept unless overwrite is set.
func WriteTo(loreDir string, overwrite bool) error {
	src := FS()
	return fs.WalkDir(src, ".", func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		dst := filepath.Join(loreDir, filepath.FromSlash(p))
		if d.IsDir() {
			return os.MkdirAll(dst, 0o755)
		}
		if !overwrite {
			if _, err := os.Stat(dst); err == nil {
				return nil
			}
		}
		data, err := fs.ReadFile(src, p)
		if err != nil {
			return err
		}
		return os.WriteFile(dst, data, 0o644)
	})
}
