package chunk

import (
	"strings"
	"testing"
)

func TestSplitByHeadingsSkipsFencesAndFrontmatter(t *testing.T) {
	doc := "---\nname: x\n---\n# Title\nintro\n\n## A\ntext a\n```\n# not a heading\n```\n## B\ntext b\n"
	secs := Split(doc, 0)
	var heads []string
	for _, s := range secs {
		heads = append(heads, s.Heading)
	}
	if strings.Join(heads, "|") != "Title|A|B" {
		t.Fatalf("headings = %v", heads)
	}
	if !strings.Contains(secs[1].Text, "# not a heading") {
		t.Errorf("fenced line split off: %q", secs[1].Text)
	}
	if secs[0].Line != 4 {
		t.Errorf("title line = %d, want 4", secs[0].Line)
	}
}

func TestLongSectionsAreWindowed(t *testing.T) {
	body := "# Big\n" + strings.Repeat("word ", 1000)
	secs := Split(body, 800)
	if len(secs) < 5 {
		t.Fatalf("got %d windows", len(secs))
	}
	for _, s := range secs {
		if len(s.Text) > 800 {
			t.Errorf("window of %d chars", len(s.Text))
		}
	}
}
