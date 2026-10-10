package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"

	"github.com/DJRCX/lore/internal/config"
	"github.com/DJRCX/lore/internal/demo"
	"github.com/DJRCX/lore/schemas"
	"github.com/spf13/cobra"
)

const indexMD = `---
okf_version: "0.2"
type: index
title: Knowledge bundle
description: Governed team knowledge served by Lore.
---
# Knowledge

- ` + "`components/`" + ` — what parts of the code each rule governs (by file glob)
- ` + "`rules/`" + ` — policies and team conventions
- ` + "`skills/`" + ` — how-to guidance
- ` + "`procedures/`" + ` — step-by-step procedures
- ` + "`sources/`" + ` — where each item came from
- ` + "`conflicts/`" + ` — contradictions Lore has recorded
`

func initCmd() *cobra.Command {
	var withDemo, force bool
	cmd := &cobra.Command{
		Use:   "init [dir]",
		Short: "Create .lore/ in a project and print IDE MCP snippets",
		Args:  cobra.MaximumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			dir := "."
			if len(args) == 1 {
				dir = args[0]
			} else if rootFlag != "" {
				dir = rootFlag
			}
			root, err := filepath.Abs(dir)
			if err != nil {
				return err
			}
			loreDir := filepath.Join(root, config.LoreDir)
			if _, err := os.Stat(loreDir); err == nil && !force && !withDemo {
				fmt.Fprintf(cmd.OutOrStdout(), "%s already exists; nothing created.\n\n", loreDir)
			} else if withDemo {
				if err := demo.WriteTo(loreDir, force); err != nil {
					return err
				}
				fmt.Fprintf(cmd.OutOrStdout(), "Wrote the demo bundle to %s\n\n", loreDir)
			} else if err := scaffold(loreDir); err != nil {
				return err
			} else {
				fmt.Fprintf(cmd.OutOrStdout(), "Created %s\n\n", loreDir)
			}
			if err := writeSchema(loreDir); err != nil {
				return err
			}
			return printSnippets(cmd.OutOrStdout(), root)
		},
	}
	cmd.Flags().BoolVar(&withDemo, "demo", false, "write the demo bundle (auth rules with a deliberate conflict)")
	cmd.Flags().BoolVar(&force, "force", false, "overwrite existing files")
	return cmd
}

func scaffold(loreDir string) error {
	for _, d := range []string{"components", "rules", "skills", "procedures", "sources", "conflicts", "decisions"} {
		if err := os.MkdirAll(filepath.Join(loreDir, d), 0o755); err != nil {
			return err
		}
	}
	cfg, err := config.Marshal(config.Default())
	if err != nil {
		return err
	}
	files := map[string][]byte{
		"index.md":      []byte(indexMD),
		"log.md":        fmt.Appendf(nil, "---\ntype: log\ntitle: Bundle changelog\n---\n- %s Bundle created.\n", time.Now().Format("2006-01-02")),
		config.FileName: cfg,
	}
	for name, data := range files {
		p := filepath.Join(loreDir, name)
		if _, err := os.Stat(p); err == nil {
			continue
		}
		if err := os.WriteFile(p, data, 0o644); err != nil {
			return err
		}
	}
	return nil
}

func writeSchema(loreDir string) error {
	dir := filepath.Join(loreDir, "schemas")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(dir, schemas.ResultV1Name), schemas.ResultV1, 0o644)
}

func printSnippets(w io.Writer, root string) error {
	bin, err := os.Executable()
	if err != nil {
		bin = "lore"
	}
	show := func(title, where string, v any) {
		raw, _ := json.MarshalIndent(v, "", "  ")
		fmt.Fprintf(w, "%s — %s\n%s\n\n", title, where, raw)
	}
	stdio := func(args ...string) map[string]any {
		return map[string]any{"command": bin, "args": args}
	}
	show("Cursor", ".cursor/mcp.json in the project", map[string]any{
		"mcpServers": map[string]any{"lore": stdio("serve", "--root", "${workspaceFolder}")},
	})
	show("VS Code (Copilot agent mode)", ".vscode/mcp.json in the project", map[string]any{
		"servers": map[string]any{"lore": map[string]any{"type": "stdio", "command": bin, "args": []string{"serve", "--root", "${workspaceFolder}"}}},
	})
	show("Antigravity", ".agents/mcp_config.json in the project, or ~/.gemini/config/mcp_config.json (agent panel → … → MCP Servers → Manage → View raw config)", map[string]any{
		"mcpServers": map[string]any{"lore": stdio("serve", "--root", root)},
	})
	show("Claude Desktop", "~/.config/Claude/claude_desktop_config.json (Linux) — restart the app after editing", map[string]any{
		"mcpServers": map[string]any{"lore": stdio("serve", "--root", root)},
	})
	fmt.Fprintln(w, "More clients: docs/ide/. Check the server by hand with:")
	fmt.Fprintf(w, "  npx @modelcontextprotocol/inspector %s serve --root %s\n", bin, root)
	return nil
}
