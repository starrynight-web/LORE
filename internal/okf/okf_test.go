package okf

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const ruleDoc = `---
type: rule
title: Access token expiry
description: Access tokens must expire within 15 minutes.
status: stable
modality: must
applies_to: [component:auth]
supersedes: rule:auth/jwt-expiry@v2
effective_from: 2026-07-01
stale_after: 2027-01-01
---
Access tokens issued by any service MUST expire in 15 minutes or less.
`

func TestParseRule(t *testing.T) {
	d, err := Parse("rules/auth/jwt-expiry@v3.md", []byte(ruleDoc))
	if err != nil {
		t.Fatal(err)
	}
	if d.ID != "rule:auth/jwt-expiry@v3" {
		t.Errorf("id = %q", d.ID)
	}
	if d.Front.EffectiveFrom != "2026-07-01" || d.Front.StaleAfter != "2027-01-01" {
		t.Errorf("dates not decoded as strings: %+v", d.Front)
	}
	if d.BodyLine != 12 {
		t.Errorf("body line = %d, want 12", d.BodyLine)
	}
	if d.Text() != "Access tokens must expire within 15 minutes." {
		t.Errorf("text = %q", d.Text())
	}
}

func TestIDs(t *testing.T) {
	cases := map[string]string{
		"rules/auth/jwt-expiry@v3.md":    "rule:auth/jwt-expiry@v3",
		"skills/go/error-wrapping@v2.md": "skill:go/error-wrapping@v2",
		"components/auth.md":             "component:auth",
		"sources/policies-auth-md.md":    "src:policies-auth-md",
		"conflicts/conf-0031.md":         "conf-0031",
		"notes/random.md":                "",
	}
	for in, want := range cases {
		if got := IDFromPath(in); got != want {
			t.Errorf("IDFromPath(%q) = %q, want %q", in, got, want)
		}
	}
	base, n := SplitVersion("rule:auth/jwt-expiry@v3")
	if base != "rule:auth/jwt-expiry" || n != 3 {
		t.Errorf("SplitVersion = %q %d", base, n)
	}
	if dir, rest, ok := DirForID("skill:go/error-wrapping@v2"); !ok || dir != "skills" || rest != "go/error-wrapping@v2" {
		t.Errorf("DirForID = %q %q %v", dir, rest, ok)
	}
}

func TestMissingFrontmatter(t *testing.T) {
	if _, err := Parse("rules/x.md", []byte("just text")); err == nil {
		t.Fatal("expected error")
	}
}

func TestSetFieldKeepsOtherKeys(t *testing.T) {
	p := filepath.Join(t.TempDir(), "r.md")
	if err := os.WriteFile(p, []byte(strings.Replace(ruleDoc, "status: stable", "status: draft", 1)), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := SetField(p, "status", "stable"); err != nil {
		t.Fatal(err)
	}
	data, _ := os.ReadFile(p)
	d, err := Parse("rules/auth/jwt-expiry@v3.md", data)
	if err != nil {
		t.Fatal(err)
	}
	if d.Front.Status != "stable" || d.Front.Supersedes != "rule:auth/jwt-expiry@v2" || len(d.Front.AppliesTo) != 1 {
		t.Errorf("unexpected front after SetField: %+v", d.Front)
	}
	if !strings.Contains(d.Body, "MUST expire") {
		t.Error("body lost")
	}
}
