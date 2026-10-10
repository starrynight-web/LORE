// Package config loads lore.config.yaml and resolves the project root.
package config

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"gopkg.in/yaml.v3"
)

const (
	// LoreDir is the bundle directory name inside a project root.
	LoreDir = ".lore"
	// FileName is the config file inside the bundle directory.
	FileName = "lore.config.yaml"
	// EnvRoot overrides the project root when --root is not given.
	EnvRoot = "LORE_ROOT"
)

type Confidence struct {
	High      float64 `yaml:"high"`
	MediumMin float64 `yaml:"medium_min"`
}

type Ports struct {
	GUI    int `yaml:"gui"`
	API    int `yaml:"api"`
	Worker int `yaml:"worker"`
}

type Config struct {
	ResultSchema          string     `yaml:"result_schema"`
	TokenBudget           int        `yaml:"token_budget"`
	MaxItems              int        `yaml:"max_items"`
	KeywordTopK           int        `yaml:"keyword_top_k"`
	VectorTopK            int        `yaml:"vector_top_k"`
	RRFK                  int        `yaml:"rrf_k"`
	GraphHops             int        `yaml:"graph_hops"`
	Confidence            Confidence `yaml:"confidence"`
	AbstainBand           [2]float64 `yaml:"abstain_band"`
	ConflictMinConfidence float64    `yaml:"conflict_min_confidence"`
	ExtractMinConfidence  float64    `yaml:"extract_min_confidence"`
	OCRMinConfidence      float64    `yaml:"ocr_min_confidence"`
	AgingWindowDays       int        `yaml:"aging_window_days"`
	ToolTimeoutSeconds    int        `yaml:"tool_timeout_seconds"`
	MaxUploadMB           int        `yaml:"max_upload_mb"`
	SearchLimit           int        `yaml:"search_limit"`
	Ports                 Ports      `yaml:"ports"`
}

// Default returns the defaults from docs/LORE_ARCHITECTURE.md.
func Default() Config {
	return Config{
		ResultSchema:          "lore.result/1",
		TokenBudget:           800,
		MaxItems:              8,
		KeywordTopK:           20,
		VectorTopK:            20,
		RRFK:                  60,
		GraphHops:             2,
		Confidence:            Confidence{High: 0.80, MediumMin: 0.55},
		AbstainBand:           [2]float64{0.45, 0.55},
		ConflictMinConfidence: 0.70,
		ExtractMinConfidence:  0.60,
		OCRMinConfidence:      0.80,
		AgingWindowDays:       14,
		ToolTimeoutSeconds:    10,
		MaxUploadMB:           50,
		SearchLimit:           20,
		Ports:                 Ports{GUI: 7420, API: 7421, Worker: 8080},
	}
}

// Load reads <loreDir>/lore.config.yaml over the defaults. A missing file is not an error.
func Load(loreDir string) (Config, error) {
	cfg := Default()
	data, err := os.ReadFile(filepath.Join(loreDir, FileName))
	if errors.Is(err, os.ErrNotExist) {
		return cfg, nil
	}
	if err != nil {
		return cfg, err
	}
	if err := yaml.Unmarshal(data, &cfg); err != nil {
		return cfg, fmt.Errorf("parse %s: %w", FileName, err)
	}
	return cfg, nil
}

// Marshal renders the config as YAML (used by `lore init`).
func Marshal(cfg Config) ([]byte, error) { return yaml.Marshal(cfg) }

// ErrNoRoot is returned when no .lore directory can be found.
var ErrNoRoot = errors.New("no .lore directory found; run `lore init` in your project or pass --root")

// FindRoot resolves the project root: explicit flag, then $LORE_ROOT, then the
// nearest ancestor of the working directory that contains .lore/.
func FindRoot(flagRoot string) (string, error) {
	for _, candidate := range []string{flagRoot, os.Getenv(EnvRoot)} {
		// Some MCP clients pass ${workspaceFolder} through unexpanded.
		if candidate == "" || strings.Contains(candidate, "${") {
			continue
		}
		abs, err := filepath.Abs(candidate)
		if err != nil {
			return "", err
		}
		if !isDir(filepath.Join(abs, LoreDir)) {
			return "", fmt.Errorf("%s has no %s directory; run `lore init` there first", abs, LoreDir)
		}
		return abs, nil
	}
	dir, err := os.Getwd()
	if err != nil {
		return "", err
	}
	for {
		if isDir(filepath.Join(dir, LoreDir)) {
			return dir, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return "", ErrNoRoot
		}
		dir = parent
	}
}

func isDir(p string) bool {
	st, err := os.Stat(p)
	return err == nil && st.IsDir()
}
