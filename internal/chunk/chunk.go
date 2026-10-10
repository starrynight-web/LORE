// Package chunk splits Markdown into heading-anchored sections.
package chunk

import (
	"strings"
)

// Section is a contiguous block of a document starting at Line (1-based).
type Section struct {
	Heading string
	Level   int
	Line    int
	Text    string
}

// Split cuts content at Markdown headings (ignoring fenced code). Sections
// longer than maxChars are cut into windows with a small overlap so search
// snippets stay short. YAML frontmatter is skipped.
func Split(content string, maxChars int) []Section {
	lines := strings.Split(content, "\n")
	start := 0
	if len(lines) > 0 && strings.TrimSpace(lines[0]) == "---" {
		for i := 1; i < len(lines); i++ {
			if strings.TrimSpace(lines[i]) == "---" {
				start = i + 1
				break
			}
		}
	}
	var out []Section
	cur := Section{Line: start + 1}
	var buf []string
	flush := func() {
		text := strings.TrimSpace(strings.Join(buf, "\n"))
		if text != "" || cur.Heading != "" {
			cur.Text = text
			out = append(out, window(cur, maxChars)...)
		}
		buf = nil
	}
	inFence := false
	for i := start; i < len(lines); i++ {
		l := lines[i]
		trim := strings.TrimSpace(l)
		if strings.HasPrefix(trim, "```") || strings.HasPrefix(trim, "~~~") {
			inFence = !inFence
		}
		if !inFence {
			if lvl, h := heading(trim); lvl > 0 {
				flush()
				cur = Section{Heading: h, Level: lvl, Line: i + 1}
				continue
			}
		}
		buf = append(buf, l)
	}
	flush()
	return out
}

func heading(line string) (int, string) {
	if !strings.HasPrefix(line, "#") {
		return 0, ""
	}
	lvl := 0
	for lvl < len(line) && line[lvl] == '#' {
		lvl++
	}
	if lvl > 6 || lvl >= len(line) || line[lvl] != ' ' {
		return 0, ""
	}
	return lvl, strings.TrimSpace(strings.TrimRight(line[lvl:], "#"))
}

func window(s Section, maxChars int) []Section {
	if maxChars <= 0 || len(s.Text) <= maxChars {
		return []Section{s}
	}
	overlap := maxChars / 8
	var out []Section
	text := s.Text
	line := s.Line
	for len(text) > 0 {
		end := maxChars
		if end >= len(text) {
			end = len(text)
		} else if cut := strings.LastIndex(text[:end], "\n"); cut > maxChars/2 {
			end = cut
		}
		part := Section{Heading: s.Heading, Level: s.Level, Line: line, Text: strings.TrimSpace(text[:end])}
		out = append(out, part)
		if end == len(text) {
			break
		}
		next := end - overlap
		if next <= 0 {
			next = end
		}
		line += strings.Count(text[:next], "\n")
		text = text[next:]
	}
	return out
}

// Headings lists headings up to maxLevel with their line numbers.
func Headings(content string, maxLevel int) []Section {
	var out []Section
	for _, s := range Split(content, 0) {
		if s.Heading != "" && s.Level <= maxLevel {
			out = append(out, Section{Heading: s.Heading, Level: s.Level, Line: s.Line})
		}
	}
	return out
}
