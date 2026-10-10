// Package skills imports SKILL.md folders into the OKF bundle without an LLM.
// Each skill becomes one short skill entry plus a source record; the raw
// folder is copied to .lore/_staging/ untouched and is what search chunks and
// the lore://skills/ resource serve.
package skills

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/DJRCX/lore/internal/chunk"
	"github.com/DJRCX/lore/internal/okf"
	"github.com/DJRCX/lore/internal/text"
	"gopkg.in/yaml.v3"
)

const (
	skillFile     = "SKILL.md"
	maxFileBytes  = 5 << 20
	maxTotalBytes = 50 << 20
	// GlobalComponent applies to every file; items on it need a keyword match to be served.
	GlobalComponent = "component:global"
)

var validAuthority = map[string]bool{"policy": true, "team_convention": true, "procedure": true, "reviewed": true, "draft": true}

type Options struct {
	Stable    bool
	Authority string
	AppliesTo []string
	Owner     string
	Now       func() time.Time
}

type Result struct {
	Name   string `json:"name"`
	ID     string `json:"id,omitempty"`
	Action string `json:"action"` // imported | updated | unchanged | duplicate | skipped
	From   string `json:"from"`
	Note   string `json:"note,omitempty"`
}

// Find returns skill folders under path: path itself if it holds SKILL.md,
// otherwise its immediate subdirectories that do.
func Find(path string) ([]string, error) {
	st, err := os.Stat(path)
	if err != nil {
		return nil, err
	}
	if !st.IsDir() {
		return nil, fmt.Errorf("%s is not a directory", path)
	}
	if fileExists(filepath.Join(path, skillFile)) {
		return []string{path}, nil
	}
	entries, err := os.ReadDir(path)
	if err != nil {
		return nil, err
	}
	var out []string
	for _, e := range entries {
		p := filepath.Join(path, e.Name())
		if strings.HasPrefix(e.Name(), ".") {
			continue
		}
		if st, err := os.Stat(p); err == nil && st.IsDir() && fileExists(filepath.Join(p, skillFile)) {
			out = append(out, p)
		}
	}
	return out, nil
}

// Import imports every skill folder found under paths.
func Import(loreDir string, paths []string, opts Options) ([]Result, error) {
	if opts.Authority == "" {
		opts.Authority = "reviewed"
	}
	if !validAuthority[opts.Authority] {
		return nil, fmt.Errorf("authority %q is not one of policy, team_convention, procedure, reviewed, draft", opts.Authority)
	}
	if len(opts.AppliesTo) == 0 {
		opts.AppliesTo = []string{GlobalComponent}
	}
	if opts.Now == nil {
		opts.Now = time.Now
	}
	seenReal := map[string]string{}
	seenSum := map[string]string{}
	var results []Result
	for _, p := range paths {
		folders, err := Find(p)
		if err != nil {
			return results, err
		}
		if len(folders) == 0 {
			results = append(results, Result{From: p, Action: "skipped", Note: "no SKILL.md found here or one level below"})
		}
		for _, f := range folders {
			results = append(results, importOne(loreDir, f, opts, seenReal, seenSum))
		}
	}
	for _, id := range opts.AppliesTo {
		if id == GlobalComponent {
			if err := ensureGlobal(loreDir); err != nil {
				return results, err
			}
		}
	}
	return results, nil
}

type skillFront struct {
	Name        string `yaml:"name"`
	Description string `yaml:"description"`
}

func importOne(loreDir, folder string, opts Options, seenReal, seenSum map[string]string) Result {
	res := Result{From: folder}
	real, err := filepath.EvalSymlinks(folder)
	if err != nil {
		return fail(res, err)
	}
	if first, ok := seenReal[real]; ok {
		res.Action, res.Note = "duplicate", "same folder as "+first
		return res
	}
	seenReal[real] = folder

	files, err := listFiles(real)
	if err != nil {
		return fail(res, err)
	}
	sum, err := checksum(real, files)
	if err != nil {
		return fail(res, err)
	}
	raw, err := os.ReadFile(filepath.Join(real, skillFile))
	if err != nil {
		return fail(res, err)
	}
	front, body := parseSkill(raw)
	name := text.Slug(front.Name)
	if name == "" {
		name = text.Slug(filepath.Base(folder))
	}
	res.Name = name
	if first, ok := seenSum[sum]; ok {
		res.Action, res.Note = "duplicate", "identical content to "+first
		return res
	}
	seenSum[sum] = folder

	prevN, prevSum := latest(loreDir, name)
	if prevN > 0 && prevSum == "sha256:"+sum {
		res.Action, res.ID = "unchanged", fmt.Sprintf("skill:%s@v%d", name, prevN)
		return res
	}
	n := prevN + 1
	ver := fmt.Sprintf("%s@v%d", name, n)
	staged := filepath.ToSlash(filepath.Join("_staging", "skills", ver))
	if err := copyFiles(real, filepath.Join(loreDir, filepath.FromSlash(staged)), files); err != nil {
		return fail(res, err)
	}

	desc := front.Description
	if desc == "" {
		desc = firstParagraph(body)
	}
	today := opts.Now().Format("2006-01-02")
	src := okf.Front{
		Type: "source", Title: "Skill folder: " + name, Description: text.FirstSentence(desc, 200),
		Path: folder, Connector: "skill_dir", Authority: opts.Authority, Owner: opts.Owner,
		Checksum: "sha256:" + sum, Staged: staged, Files: files, Generated: today,
	}
	if err := writeDoc(filepath.Join(loreDir, "sources", "skill-"+ver+".md"), src, ""); err != nil {
		return fail(res, err)
	}

	heads := chunk.Headings(string(raw), 3)
	status := "draft"
	if opts.Stable {
		status = "stable"
	}
	entry := okf.Front{
		Type: "skill", Title: firstNonEmpty(front.Name, name), Description: text.FirstSentence(desc, 200),
		Status: status, Modality: "should", Severity: "low", Authority: opts.Authority,
		AppliesTo: opts.AppliesTo, SourceID: "src:skill-" + ver, Anchor: skillFile + "#L1",
		Origin: "human_authored", Owner: opts.Owner, Tags: tags(name, heads), Generated: today,
		Resource: "lore://sources/skill-" + ver + "/" + skillFile,
	}
	if prevN > 0 {
		entry.Supersedes = fmt.Sprintf("skill:%s@v%d", name, prevN)
	}
	if err := writeDoc(filepath.Join(loreDir, "skills", ver+".md"), entry, toc(ver, heads)); err != nil {
		return fail(res, err)
	}
	res.ID = "skill:" + ver
	res.Action = "imported"
	if prevN > 0 {
		res.Action = "updated"
	}
	if !opts.Stable {
		res.Note = "draft; run `lore promote " + res.ID + "` to serve it"
	}
	return res
}

func fail(r Result, err error) Result {
	r.Action, r.Note = "skipped", err.Error()
	return r
}

func parseSkill(raw []byte) (skillFront, string) {
	var f skillFront
	fm, body, _, err := okf.Split(raw)
	if err != nil {
		return f, string(raw)
	}
	_ = yaml.Unmarshal(fm, &f)
	return f, body
}

func firstParagraph(body string) string {
	for _, s := range chunk.Split(body, 0) {
		for _, para := range strings.Split(s.Text, "\n\n") {
			if p := strings.TrimSpace(para); p != "" && !strings.HasPrefix(p, "```") {
				return p
			}
		}
	}
	return ""
}

func firstNonEmpty(a ...string) string {
	for _, s := range a {
		if s != "" {
			return s
		}
	}
	return ""
}

// tags are the strong keywords for retrieval: the name parts plus heading terms.
func tags(name string, heads []chunk.Section) []string {
	seen := map[string]bool{}
	out := []string{"skill"}
	seen["skill"] = true
	add := func(t string) {
		if !seen[t] && len(out) < 16 {
			seen[t] = true
			out = append(out, t)
		}
	}
	for _, t := range text.Terms(strings.ReplaceAll(name, "-", " ")) {
		add(t)
	}
	for _, h := range heads {
		if h.Level > 2 {
			continue
		}
		for _, t := range text.Terms(h.Heading) {
			add(t)
		}
	}
	return out
}

func toc(ver string, heads []chunk.Section) string {
	var b strings.Builder
	fmt.Fprintf(&b, "Imported skill. Full text: lore://skills/%s\n", ver)
	if len(heads) == 0 {
		return b.String()
	}
	b.WriteString("\n## Sections\n")
	for _, h := range heads {
		fmt.Fprintf(&b, "%s- %s (%s#L%d)\n", strings.Repeat("  ", h.Level-1), h.Heading, skillFile, h.Line)
	}
	return b.String()
}

// latest returns the highest imported version of name and its source checksum.
func latest(loreDir, name string) (int, string) {
	matches, _ := filepath.Glob(filepath.Join(loreDir, "skills", name+"@v*.md"))
	max := 0
	for _, m := range matches {
		_, n := okf.SplitVersion("skill:" + strings.TrimSuffix(filepath.Base(m), ".md"))
		if n > max {
			max = n
		}
	}
	if max == 0 {
		return 0, ""
	}
	data, err := os.ReadFile(filepath.Join(loreDir, "sources", fmt.Sprintf("skill-%s@v%d.md", name, max)))
	if err != nil {
		return max, ""
	}
	d, err := okf.Parse("sources/x.md", data)
	if err != nil {
		return max, ""
	}
	return max, d.Front.Checksum
}

func listFiles(root string) ([]string, error) {
	var files []string
	var total int64
	err := filepath.WalkDir(root, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		name := d.Name()
		if p != root && strings.HasPrefix(name, ".") {
			if d.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		if d.IsDir() || !d.Type().IsRegular() {
			return nil
		}
		info, err := d.Info()
		if err != nil {
			return err
		}
		if info.Size() > maxFileBytes {
			return nil
		}
		total += info.Size()
		if total > maxTotalBytes {
			return errors.New("skill folder is larger than 50 MB")
		}
		rel, _ := filepath.Rel(root, p)
		files = append(files, filepath.ToSlash(rel))
		return nil
	})
	sort.Strings(files)
	return files, err
}

func checksum(root string, files []string) (string, error) {
	h := sha256.New()
	for _, f := range files {
		h.Write([]byte(f))
		h.Write([]byte{0})
		fh, err := os.Open(filepath.Join(root, filepath.FromSlash(f)))
		if err != nil {
			return "", err
		}
		_, err = io.Copy(h, fh)
		fh.Close()
		if err != nil {
			return "", err
		}
		h.Write([]byte{0})
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func copyFiles(src, dst string, files []string) error {
	for _, f := range files {
		to := filepath.Join(dst, filepath.FromSlash(f))
		if err := os.MkdirAll(filepath.Dir(to), 0o755); err != nil {
			return err
		}
		data, err := os.ReadFile(filepath.Join(src, filepath.FromSlash(f)))
		if err != nil {
			return err
		}
		if err := os.WriteFile(to, data, 0o644); err != nil {
			return err
		}
	}
	return nil
}

func writeDoc(path string, front okf.Front, body string) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	data, err := okf.Marshal(front, body)
	if err != nil {
		return err
	}
	return os.WriteFile(path, data, 0o644)
}

func ensureGlobal(loreDir string) error {
	path := filepath.Join(loreDir, "components", "global.md")
	if fileExists(path) {
		return nil
	}
	return writeDoc(path, okf.Front{
		Type: "component", Title: "Global", Status: "stable", Authority: "reviewed",
		Description: "Applies to every file; items on it are served only when the task mentions them.",
		Globs:       []string{"**"}, Origin: "human_authored",
	}, "")
}

func fileExists(p string) bool {
	st, err := os.Stat(p)
	return err == nil && !st.IsDir()
}
