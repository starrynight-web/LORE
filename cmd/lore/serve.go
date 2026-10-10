package main

import (
	"time"

	"github.com/spf13/cobra"
	"github.com/starrynight-web/LORE/internal/mcp"
)

func serveCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "serve",
		Short: "Run the MCP server on stdio (started by your IDE, not by hand)",
		Long: `Runs the Lore MCP server over stdio. IDEs start this command themselves from
their MCP config; see "lore init" for the snippet. Logs go to stderr; stdout
carries the protocol. The bundle is reloaded when files under .lore/ change.`,
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			st, cfg, err := openStore(true)
			if err != nil {
				return err
			}
			defer st.Close()
			srv := mcp.New(st, mcp.Options{
				Version: version,
				LoreDir: st.LoreDir(),
				Timeout: time.Duration(cfg.ToolTimeoutSeconds) * time.Second,
				Logger:  logger(),
			})
			return srv.Run(cmd.Context())
		},
	}
}
