package config

import (
	"os"
	"path/filepath"
	"testing"
)

func TestFindRoot(t *testing.T) {
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, LoreDir), 0o755); err != nil {
		t.Fatal(err)
	}
	sub := filepath.Join(root, "src", "auth")
	if err := os.MkdirAll(sub, 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv(EnvRoot, "")
	t.Chdir(sub)

	got, err := FindRoot("")
	if err != nil || got != root {
		t.Errorf("walk up = %q, %v", got, err)
	}
	got, err = FindRoot("${workspaceFolder}")
	if err != nil || got != root {
		t.Errorf("unexpanded variable = %q, %v", got, err)
	}
	if _, err := FindRoot(t.TempDir()); err == nil {
		t.Error("root without .lore accepted")
	}
	t.Setenv(EnvRoot, root)
	t.Chdir(t.TempDir())
	if got, err := FindRoot(""); err != nil || got != root {
		t.Errorf("env root = %q, %v", got, err)
	}
}

func TestLoadOverridesDefaults(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, FileName), []byte("token_budget: 500\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	cfg, err := Load(dir)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.TokenBudget != 500 || cfg.MaxItems != Default().MaxItems {
		t.Errorf("cfg = %+v", cfg)
	}
}
