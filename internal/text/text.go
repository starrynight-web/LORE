// Package text holds the deterministic keyword helpers shared by retrieval and import.
package text

import (
	"strings"
	"unicode"
)

var stop = map[string]bool{}

func init() {
	for _, w := range strings.Fields(`the and for with that this into from are was were will any all add use using
		must should not you your new get set can may has have its our out per via but also when then than them they
		what which who how why here there each every some more most such only very just about over under make makes
		src lib pkg cmd internal main test tests file files code tsx jsx html css json yaml md`) {
		stop[w] = true
	}
}

// Terms lowercases s, splits on non-alphanumerics, drops stop words and short
// tokens, applies a light plural stem, and returns unique terms in order.
func Terms(s string) []string {
	seen := map[string]bool{}
	var out []string
	for _, f := range strings.FieldsFunc(strings.ToLower(s), func(r rune) bool {
		return !unicode.IsLetter(r) && !unicode.IsDigit(r)
	}) {
		if len(f) < 3 || stop[f] {
			continue
		}
		f = stem(f)
		if !seen[f] {
			seen[f] = true
			out = append(out, f)
		}
	}
	return out
}

func stem(w string) string {
	switch {
	case len(w) > 5 && strings.HasSuffix(w, "ies"):
		return w[:len(w)-3] + "y"
	case len(w) > 4 && strings.HasSuffix(w, "s") && !strings.HasSuffix(w, "ss") && !strings.HasSuffix(w, "us"):
		return w[:len(w)-1]
	}
	return w
}

// Set builds a membership set from terms.
func Set(terms ...[]string) map[string]bool {
	m := map[string]bool{}
	for _, ts := range terms {
		for _, t := range ts {
			m[t] = true
		}
	}
	return m
}

// FirstSentence returns the first sentence of s, collapsed to one line and capped at max bytes.
func FirstSentence(s string, max int) string {
	s = strings.Join(strings.Fields(s), " ")
	for i := 0; i+1 < len(s); i++ {
		if (s[i] == '.' || s[i] == '!' || s[i] == '?') && s[i+1] == ' ' {
			s = s[:i+1]
			break
		}
	}
	if len(s) > max {
		cut := strings.LastIndex(s[:max-1], " ")
		if cut < max/2 {
			cut = max - 1
		}
		s = strings.TrimRight(s[:cut], " ,;:") + "…"
	}
	return s
}

// Slug lowercases s and keeps [a-z0-9-], collapsing everything else to '-'.
func Slug(s string) string {
	var b strings.Builder
	dash := false
	for _, r := range strings.ToLower(s) {
		if (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9') {
			b.WriteRune(r)
			dash = false
		} else if !dash && b.Len() > 0 {
			b.WriteByte('-')
			dash = true
		}
	}
	return strings.Trim(b.String(), "-")
}
