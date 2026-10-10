// Command lore is the Lore CLI and MCP server.
package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"github.com/DJRCX/lore/internal/config"
	"github.com/DJRCX/lore/internal/store/filestore"
	"github.com/spf13/cobra"
)

// version is set at build time with -ldflags "-X main.version=...".
var version = "dev"

// exitError carries a process exit code out of a command.
type exitError struct{ code int }

func (e exitError) Error() string { return fmt.Sprintf("exit %d", e.code) }

var rootFlag string

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	err := newRoot().ExecuteContext(ctx)
	var ee exitError
	switch {
	case err == nil:
	case errors.As(err, &ee):
		os.Exit(ee.code)
	default:
		fmt.Fprintln(os.Stderr, "lore:", err)
		os.Exit(1)
	}
}

func newRoot() *cobra.Command {
	root := &cobra.Command{
		Use:           "lore",
		Short:         "Lore serves governed team knowledge to coding agents over MCP",
		SilenceUsage:  true,
		SilenceErrors: true,
	}
	root.PersistentFlags().StringVar(&rootFlag, "root", "", "project root containing .lore/ (default: $LORE_ROOT, then the nearest parent with .lore/)")
	root.AddCommand(serveCmd(), initCmd(), contextCmd(), searchCmd(), conflictsCmd(), importCmd(), promoteCmd(), statsCmd(), traceCmd(), versionCmd())
	return root
}

func logger() *slog.Logger {
	level := slog.LevelWarn
	if os.Getenv("LORE_DEBUG") != "" {
		level = slog.LevelDebug
	}
	return slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: level}))
}

// openStore resolves the root, loads config and opens the file store.
func openStore(watch bool) (*filestore.FileStore, config.Config, error) {
	root, err := config.FindRoot(rootFlag)
	if err != nil {
		return nil, config.Config{}, err
	}
	cfg, err := config.Load(root + string(os.PathSeparator) + config.LoreDir)
	if err != nil {
		return nil, cfg, err
	}
	st, err := filestore.Open(root, cfg, filestore.Options{Watch: watch, Logger: logger()})
	return st, cfg, err
}
