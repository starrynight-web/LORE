package main

import (
	"encoding/json"
	"fmt"
	"path/filepath"
	"strings"
	"text/tabwriter"

	"github.com/DJRCX/lore/internal/config"
	"github.com/DJRCX/lore/internal/importer/skills"
	"github.com/DJRCX/lore/internal/review"
	"github.com/spf13/cobra"
)

func importCmd() *cobra.Command {
	cmd := &cobra.Command{Use: "import", Short: "Import existing knowledge into .lore/"}
	var opts skills.Options
	var asJSON bool
	sk := &cobra.Command{
		Use:   "skills <dir>...",
		Short: "Import SKILL.md folders as skills (drafts unless --stable)",
		Long: `Imports each folder containing SKILL.md, either the folder itself or its
immediate subfolders. Each skill becomes a short entry in .lore/skills/ plus a
source record; the raw folder is copied to .lore/_staging/ for search and for
the lore://skills/ resource. Imports are drafts until promoted, unless --stable.

Example: lore import skills ~/.cursor/skills ~/.agents/skills`,
		Args: cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			root, err := config.FindRoot(rootFlag)
			if err != nil {
				return err
			}
			results, err := skills.Import(filepath.Join(root, config.LoreDir), args, opts)
			if err != nil {
				return err
			}
			if asJSON {
				enc := json.NewEncoder(cmd.OutOrStdout())
				enc.SetIndent("", "  ")
				return enc.Encode(results)
			}
			tw := tabwriter.NewWriter(cmd.OutOrStdout(), 0, 4, 2, ' ', 0)
			counts := map[string]int{}
			for _, r := range results {
				counts[r.Action]++
				fmt.Fprintf(tw, "%s\t%s\t%s\n", strings.ToUpper(r.Action), firstOf(r.ID, r.Name, r.From), r.Note)
			}
			tw.Flush()
			fmt.Fprintf(cmd.OutOrStdout(), "\n%d imported, %d updated, %d unchanged, %d duplicate, %d skipped.\n",
				counts["imported"], counts["updated"], counts["unchanged"], counts["duplicate"], counts["skipped"])
			if !opts.Stable && counts["imported"]+counts["updated"] > 0 {
				fmt.Fprintln(cmd.OutOrStdout(), "Drafts are not served until promoted: lore promote <id>, or re-run with --stable.")
			}
			return nil
		},
	}
	sk.Flags().BoolVar(&opts.Stable, "stable", false, "mark imports stable so they are served immediately (you are the reviewer)")
	sk.Flags().StringVar(&opts.Authority, "authority", "reviewed", "authority: policy, team_convention, procedure, reviewed or draft")
	sk.Flags().StringSliceVar(&opts.AppliesTo, "applies-to", nil, "component IDs the skills apply to (default component:global, which needs a keyword match)")
	sk.Flags().StringVar(&opts.Owner, "owner", "", "owner handle, e.g. @platform")
	sk.Flags().BoolVar(&asJSON, "json", false, "print results as JSON")
	cmd.AddCommand(sk)
	return cmd
}

func firstOf(s ...string) string {
	for _, v := range s {
		if v != "" {
			return v
		}
	}
	return ""
}

func promoteCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "promote <id>...",
		Short: "Approve draft items so Lore serves them (human-only; not exposed over MCP)",
		Args:  cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			root, err := config.FindRoot(rootFlag)
			if err != nil {
				return err
			}
			loreDir := filepath.Join(root, config.LoreDir)
			var failed int
			for _, id := range args {
				if err := review.Promote(loreDir, id); err != nil {
					fmt.Fprintf(cmd.ErrOrStderr(), "%s: %v\n", id, err)
					failed++
					continue
				}
				fmt.Fprintf(cmd.OutOrStdout(), "promoted %s\n", id)
			}
			if failed > 0 {
				return exitError{1}
			}
			return nil
		},
	}
}
