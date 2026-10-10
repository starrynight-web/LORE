package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"

	"github.com/DJRCX/lore/internal/present"
	"github.com/DJRCX/lore/internal/result"
	"github.com/DJRCX/lore/internal/store"
	"github.com/DJRCX/lore/internal/store/filestore"
	"github.com/spf13/cobra"
)

type outputFlags struct {
	json, agent, detailed bool
}

func (o *outputFlags) register(cmd *cobra.Command) {
	cmd.Flags().BoolVar(&o.json, "json", false, "print the lore.result/1 JSON envelope")
	cmd.Flags().BoolVar(&o.agent, "agent", false, "print the <lore> block exactly as agents receive it")
	cmd.Flags().BoolVar(&o.detailed, "detailed", false, "with --agent, include anchors and probabilities")
}

func (o *outputFlags) print(w io.Writer, env *result.Envelope) error {
	switch {
	case o.json:
		enc := json.NewEncoder(w)
		enc.SetIndent("", "  ")
		enc.SetEscapeHTML(false)
		return enc.Encode(env)
	case o.agent:
		_, err := fmt.Fprintln(w, present.AgentText(env, o.detailed))
		return err
	default:
		_, err := fmt.Fprint(w, present.CLIText(env))
		return err
	}
}

// exitFor maps the directive to the exit code scripts and hooks branch on:
// 0 proceed, 3 ask the user, 4 stop.
func exitFor(env *result.Envelope) error {
	switch env.Directive {
	case result.AskUser:
		return exitError{3}
	case result.Stop:
		return exitError{4}
	}
	return nil
}

// readCmd builds a command that opens the store, runs fn and prints the envelope.
func readCmd(use, short string, args cobra.PositionalArgs, setup func(*cobra.Command), fn func(*cobra.Command, []string, *filestore.FileStore) (*result.Envelope, error), withExit bool) *cobra.Command {
	var out outputFlags
	cmd := &cobra.Command{
		Use: use, Short: short, Args: args,
		RunE: func(cmd *cobra.Command, a []string) error {
			st, _, err := openStore(false)
			if err != nil {
				return err
			}
			defer st.Close()
			env, err := fn(cmd, a, st)
			if err != nil {
				return err
			}
			if err := out.print(cmd.OutOrStdout(), env); err != nil {
				return err
			}
			if withExit {
				return exitFor(env)
			}
			return nil
		},
	}
	out.register(cmd)
	if setup != nil {
		setup(cmd)
	}
	return cmd
}

func contextCmd() *cobra.Command {
	var req store.ContextRequest
	var diff string
	return readCmd("context", "Show what Lore would tell an agent about a file (exit 3 = ask the user, 4 = stop)", cobra.NoArgs,
		func(cmd *cobra.Command) {
			cmd.Flags().StringVarP(&req.FilePath, "file", "f", "", "repo-relative file path (required unless --diff)")
			cmd.Flags().StringVarP(&req.Intent, "intent", "i", "", "one-line description of the change")
			cmd.Flags().StringVar(&req.AsOf, "as-of", "", "evaluate as of YYYY-MM-DD")
			cmd.Flags().BoolVar(&req.DryRun, "dry-run", false, "do not write a decision record")
			cmd.Flags().StringVar(&diff, "diff", "", "check a diff file against MUST rules instead (- for stdin)")
		},
		func(cmd *cobra.Command, _ []string, st *filestore.FileStore) (*result.Envelope, error) {
			detailed, _ := cmd.Flags().GetBool("detailed")
			if diff != "" {
				var data []byte
				var err error
				if diff == "-" {
					data, err = io.ReadAll(os.Stdin)
				} else {
					data, err = os.ReadFile(diff)
				}
				if err != nil {
					return nil, err
				}
				return st.Compliance(cmd.Context(), store.ComplianceRequest{Diff: string(data), FilePath: req.FilePath, Detailed: detailed, DryRun: req.DryRun})
			}
			if req.FilePath == "" {
				return nil, fmt.Errorf("--file is required, e.g. lore context --file src/auth/token.go --intent \"add refresh endpoint\"")
			}
			req.Detailed = detailed
			return st.Context(cmd.Context(), req)
		}, true)
}

func searchCmd() *cobra.Command {
	var req store.SearchRequest
	return readCmd("search <query>", "Keyword search over governed knowledge", cobra.ExactArgs(1),
		func(cmd *cobra.Command) {
			cmd.Flags().StringVar(&req.Component, "component", "", "restrict to a component ID, e.g. component:auth")
			cmd.Flags().BoolVarP(&req.IncludeUnverified, "unverified", "u", false, "also search unreviewed staged text")
			cmd.Flags().IntVarP(&req.Limit, "limit", "n", 0, "maximum results")
		},
		func(cmd *cobra.Command, args []string, st *filestore.FileStore) (*result.Envelope, error) {
			req.Query = args[0]
			return st.Search(cmd.Context(), req)
		}, false)
}

func conflictsCmd() *cobra.Command {
	var req store.ConflictsRequest
	return readCmd("conflicts [scope]", "List recorded conflicts, optionally for a component ID or file", cobra.MaximumNArgs(1),
		func(cmd *cobra.Command) {
			cmd.Flags().BoolVar(new(bool), "all", false, "include resolved and dismissed conflicts")
		},
		func(cmd *cobra.Command, args []string, st *filestore.FileStore) (*result.Envelope, error) {
			if len(args) == 1 {
				req.Scope = args[0]
			}
			if all, _ := cmd.Flags().GetBool("all"); all {
				req.Status = "all"
			}
			return st.Conflicts(cmd.Context(), req)
		}, false)
}

func statsCmd() *cobra.Command {
	return readCmd("stats", "Counts of live items, drafts, conflicts and jobs", cobra.NoArgs, nil,
		func(cmd *cobra.Command, _ []string, st *filestore.FileStore) (*result.Envelope, error) {
			env, err := st.Stats(cmd.Context())
			if err != nil {
				return nil, err
			}
			if json, _ := cmd.Flags().GetBool("json"); !json {
				if drafts, ok := env.Data["drafts"].([]string); ok && len(drafts) > 0 {
					fmt.Fprintln(cmd.OutOrStdout(), "Drafts awaiting review (lore promote <id>):")
					for _, d := range drafts {
						fmt.Fprintln(cmd.OutOrStdout(), "  "+d)
					}
				}
			}
			return env, nil
		}, false)
}

func traceCmd() *cobra.Command {
	return readCmd("trace <decision-id>", "Explain a past decision: what was used, excluded and why", cobra.ExactArgs(1), nil,
		func(cmd *cobra.Command, args []string, st *filestore.FileStore) (*result.Envelope, error) {
			return st.Trace(cmd.Context(), args[0])
		}, false)
}

func versionCmd() *cobra.Command {
	return &cobra.Command{
		Use: "version", Short: "Print the version", Args: cobra.NoArgs,
		Run: func(cmd *cobra.Command, _ []string) {
			fmt.Fprintf(cmd.OutOrStdout(), "lore %s (result schema %s)\n", version, result.SchemaID)
		},
	}
}
