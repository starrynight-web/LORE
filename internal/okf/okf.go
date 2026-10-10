// Package okf reads and writes OKF v0.2 documents with Lore frontmatter extensions.
package okf

import (
	"bytes"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"gopkg.in/yaml.v3"
)

// Front is the union of OKF native fields and Lore extensions used by every
// document type. Unused fields stay empty.
type Front struct {
	ID          string   `yaml:"id,omitempty"`
	Type        string   `yaml:"type"`
	Title       string   `yaml:"title,omitempty"`
	Description string   `yaml:"description,omitempty"`
	Status      string   `yaml:"status,omitempty"`
	Resource    string   `yaml:"resource,omitempty"`
	Tags        []string `yaml:"tags,omitempty"`
	Sources     []string `yaml:"sources,omitempty"`
	Generated   string   `yaml:"generated,omitempty"`
	Verified    string   `yaml:"verified,omitempty"`
	StaleAfter  string   `yaml:"stale_after,omitempty"`

	Modality      string   `yaml:"modality,omitempty"`
	Severity      string   `yaml:"severity,omitempty"`
	Authority     string   `yaml:"authority,omitempty"`
	Precedence    int      `yaml:"precedence,omitempty"`
	AppliesTo     []string `yaml:"applies_to,omitempty"`
	DependsOn     []string `yaml:"depends_on,omitempty"`
	Exempts       []string `yaml:"exempts,omitempty"`
	SupportedBy   []string `yaml:"supported_by,omitempty"`
	Supersedes    string   `yaml:"supersedes,omitempty"`
	EffectiveFrom string   `yaml:"effective_from,omitempty"`
	EffectiveTo   string   `yaml:"effective_to,omitempty"`
	SourceID      string   `yaml:"source_id,omitempty"`
	Anchor        string   `yaml:"anchor,omitempty"`
	Origin        string   `yaml:"origin,omitempty"`
	Owner         string   `yaml:"owner,omitempty"`
	Residency     []string `yaml:"residency,omitempty"`

	// Component
	Name    string   `yaml:"name,omitempty"`
	Aliases []string `yaml:"aliases,omitempty"`
	Globs   []string `yaml:"globs,omitempty"`

	// Source
	Path      string   `yaml:"path,omitempty"`
	Connector string   `yaml:"connector,omitempty"`
	Checksum  string   `yaml:"checksum,omitempty"`
	Staged    string   `yaml:"staged,omitempty"`
	Files     []string `yaml:"files,omitempty"`

	// Conflict
	LeftRule            string   `yaml:"left_rule,omitempty"`
	RightRule           string   `yaml:"right_rule,omitempty"`
	Kind                string   `yaml:"kind,omitempty"`
	ScopeOverlap        string   `yaml:"scope_overlap,omitempty"`
	TemporalStatus      string   `yaml:"temporal_status,omitempty"`
	AuthorityComparison string   `yaml:"authority_comparison,omitempty"`
	Evidence            []string `yaml:"evidence,omitempty"`
	Confidence          float64  `yaml:"confidence,omitempty"`
	Decision            string   `yaml:"decision,omitempty"`
	Resolution          string   `yaml:"resolution,omitempty"`
	ResolvedBy          string   `yaml:"resolved_by,omitempty"`
	ResolvedAt          string   `yaml:"resolved_at,omitempty"`
	Note                string   `yaml:"note,omitempty"`
}

// Doc is one parsed OKF file.
type Doc struct {
	ID       string
	Path     string // relative to the .lore directory, slash-separated
	Front    Front
	Body     string
	BodyLine int // 1-based line where the body starts
}

// Text returns the one-line statement used in results: the description if
// present, else the body.
func (d *Doc) Text() string {
	if d.Front.Description != "" {
		return d.Front.Description
	}
	return strings.TrimSpace(d.Body)
}

var errNoFrontmatter = errors.New("missing YAML frontmatter")

// Split separates YAML frontmatter from the Markdown body.
func Split(data []byte) (front []byte, body string, bodyLine int, err error) {
	data = bytes.TrimPrefix(data, []byte("\ufeff"))
	if !bytes.HasPrefix(data, []byte("---\n")) && !bytes.HasPrefix(data, []byte("---\r\n")) {
		return nil, string(data), 1, errNoFrontmatter
	}
	lines := strings.SplitAfter(string(data), "\n")
	for i := 1; i < len(lines); i++ {
		if strings.TrimRight(lines[i], "\r\n") == "---" {
			return []byte(strings.Join(lines[1:i], "")), strings.Join(lines[i+1:], ""), i + 2, nil
		}
	}
	return nil, string(data), 1, errors.New("unterminated YAML frontmatter")
}

// Parse decodes one OKF document. rel is the path relative to the .lore directory.
func Parse(rel string, data []byte) (*Doc, error) {
	fm, body, line, err := Split(data)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", rel, err)
	}
	var f Front
	if err := yaml.Unmarshal(fm, &f); err != nil {
		return nil, fmt.Errorf("%s: %w", rel, err)
	}
	rel = filepath.ToSlash(rel)
	d := &Doc{Path: rel, Front: f, Body: body, BodyLine: line}
	d.ID = f.ID
	if d.ID == "" {
		d.ID = IDFromPath(rel)
	}
	if d.ID == "" {
		return nil, fmt.Errorf("%s: cannot derive an id; add an `id:` field", rel)
	}
	return d, nil
}

// prefixes maps bundle directories to semantic ID prefixes.
var prefixes = map[string]string{
	"rules":      "rule:",
	"skills":     "skill:",
	"procedures": "procedure:",
	"components": "component:",
	"sources":    "src:",
	"conflicts":  "",
	"decisions":  "",
}

// TypeDirs lists bundle directories that hold knowledge documents.
var TypeDirs = []string{"components", "rules", "skills", "procedures", "sources", "conflicts"}

// IDFromPath derives a semantic ID: rules/auth/jwt-expiry@v3.md -> rule:auth/jwt-expiry@v3.
func IDFromPath(rel string) string {
	rel = filepath.ToSlash(rel)
	dir, rest, ok := strings.Cut(rel, "/")
	if !ok {
		return ""
	}
	prefix, known := prefixes[dir]
	if !known {
		return ""
	}
	return prefix + strings.TrimSuffix(rest, ".md")
}

// DirForID is the inverse of IDFromPath for knowledge item IDs.
func DirForID(id string) (dir, rest string, ok bool) {
	for d, p := range prefixes {
		if p != "" && strings.HasPrefix(id, p) {
			return d, strings.TrimPrefix(id, p), true
		}
	}
	return "", "", false
}

var versionRe = regexp.MustCompile(`^(.*)@v(\d+)$`)

// SplitVersion splits "rule:auth/jwt-expiry@v3" into ("rule:auth/jwt-expiry", 3).
// IDs without a version return n = 0.
func SplitVersion(id string) (base string, n int) {
	m := versionRe.FindStringSubmatch(id)
	if m == nil {
		return id, 0
	}
	n, _ = strconv.Atoi(m[2])
	return m[1], n
}

// LoadBundle parses every knowledge document under loreDir. Parse errors are
// returned alongside the documents that did load, so one bad file does not
// take the server down.
func LoadBundle(loreDir string) ([]*Doc, []error) {
	var docs []*Doc
	var errs []error
	for _, dir := range TypeDirs {
		root := filepath.Join(loreDir, dir)
		_ = filepath.WalkDir(root, func(p string, de fs.DirEntry, err error) error {
			if err != nil {
				if !errors.Is(err, fs.ErrNotExist) {
					errs = append(errs, err)
				}
				return nil
			}
			if de.IsDir() || !strings.HasSuffix(p, ".md") {
				return nil
			}
			data, err := os.ReadFile(p)
			if err != nil {
				errs = append(errs, err)
				return nil
			}
			rel, _ := filepath.Rel(loreDir, p)
			d, err := Parse(rel, data)
			if err != nil {
				errs = append(errs, err)
				return nil
			}
			docs = append(docs, d)
			return nil
		})
	}
	sort.Slice(docs, func(i, j int) bool { return docs[i].Path < docs[j].Path })
	return docs, errs
}

// Marshal renders frontmatter and body as an OKF document.
func Marshal(front any, body string) ([]byte, error) {
	var buf bytes.Buffer
	buf.WriteString("---\n")
	enc := yaml.NewEncoder(&buf)
	enc.SetIndent(2)
	if err := enc.Encode(front); err != nil {
		return nil, err
	}
	_ = enc.Close()
	buf.WriteString("---\n")
	buf.WriteString(body)
	if body != "" && !strings.HasSuffix(body, "\n") {
		buf.WriteString("\n")
	}
	return buf.Bytes(), nil
}

// SetField rewrites one top-level frontmatter key in place, keeping the order
// and comments of every other key.
func SetField(path, key, value string) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	fm, body, _, err := Split(data)
	if err != nil {
		return err
	}
	var node yaml.Node
	if err := yaml.Unmarshal(fm, &node); err != nil {
		return err
	}
	if len(node.Content) == 0 || node.Content[0].Kind != yaml.MappingNode {
		return fmt.Errorf("%s: frontmatter is not a mapping", path)
	}
	m := node.Content[0]
	found := false
	for i := 0; i+1 < len(m.Content); i += 2 {
		if m.Content[i].Value == key {
			m.Content[i+1].SetString(value)
			found = true
			break
		}
	}
	if !found {
		k := &yaml.Node{}
		k.SetString(key)
		v := &yaml.Node{}
		v.SetString(value)
		m.Content = append(m.Content, k, v)
	}
	out, err := Marshal(&node, body)
	if err != nil {
		return err
	}
	return os.WriteFile(path, out, 0o644)
}
