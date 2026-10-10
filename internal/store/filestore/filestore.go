// Package filestore implements store.Store directly over the .lore OKF bundle,
// held in memory and reloaded on change. It covers the deterministic parts of
// GraphRAG (component mapping, keyword seeds, graph expansion, temporal and
// authority filters, recorded conflicts) without Neo4j or Jev.
package filestore

import (
	"crypto/sha256"
	"encoding/hex"
	"io/fs"
	"log/slog"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/DJRCX/lore/internal/config"
	"github.com/DJRCX/lore/internal/lineage"
	"github.com/DJRCX/lore/internal/okf"
	"github.com/DJRCX/lore/internal/result"
	"github.com/DJRCX/lore/internal/store"
	"github.com/DJRCX/lore/internal/text"
	"github.com/fsnotify/fsnotify"
)

type Options struct {
	Watch  bool
	Logger *slog.Logger
	Now    func() time.Time
}

type FileStore struct {
	root    string
	loreDir string
	cfg     config.Config
	rec     *lineage.Recorder
	log     *slog.Logger
	now     func() time.Time

	mu        sync.RWMutex
	snap      *snapshot
	listeners []func()

	jobsMu  sync.Mutex
	watcher *fsnotify.Watcher
	done    chan struct{}
}

var _ store.Store = (*FileStore)(nil)

// Open loads the bundle under root/.lore.
func Open(root string, cfg config.Config, opts Options) (*FileStore, error) {
	if opts.Logger == nil {
		opts.Logger = slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelWarn}))
	}
	if opts.Now == nil {
		opts.Now = time.Now
	}
	loreDir := filepath.Join(root, config.LoreDir)
	s := &FileStore{
		root: root, loreDir: loreDir, cfg: cfg,
		rec: lineage.NewRecorder(loreDir), log: opts.Logger, now: opts.Now,
		done: make(chan struct{}),
	}
	if err := s.Reload(); err != nil {
		return nil, err
	}
	if opts.Watch {
		if err := s.watch(); err != nil {
			s.log.Warn("file watching disabled", "err", err)
		}
	}
	return s, nil
}

func (s *FileStore) Root() string    { return s.root }
func (s *FileStore) LoreDir() string { return s.loreDir }

func (s *FileStore) OnChange(fn func()) {
	s.mu.Lock()
	s.listeners = append(s.listeners, fn)
	s.mu.Unlock()
}

func (s *FileStore) Close() error {
	select {
	case <-s.done:
	default:
		close(s.done)
	}
	if s.watcher != nil {
		return s.watcher.Close()
	}
	return nil
}

func (s *FileStore) current() *snapshot {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.snap
}

// Reload rebuilds the in-memory snapshot from disk.
func (s *FileStore) Reload() error {
	snap := build(s.loreDir)
	for _, err := range snap.loadErrs {
		s.log.Warn("skipped invalid OKF document", "err", err)
	}
	s.mu.Lock()
	s.snap = snap
	listeners := append([]func(){}, s.listeners...)
	s.mu.Unlock()
	for _, fn := range listeners {
		fn()
	}
	return nil
}

// snapshot is an immutable view of the bundle.
type snapshot struct {
	byID         map[string]*okf.Doc
	items        []*okf.Doc // rules, skills, procedures
	components   []*okf.Doc
	sources      map[string]*okf.Doc
	conflicts    []*okf.Doc
	supersededBy map[string]string
	versions     map[string][]*okf.Doc // base id -> docs sorted by version
	strong       map[string]map[string]bool
	weak         map[string]map[string]bool
	chunks       []chunkRec
	hash         string
	loadErrs     []error
}

func build(loreDir string) *snapshot {
	docs, errs := okf.LoadBundle(loreDir)
	sn := &snapshot{
		byID: map[string]*okf.Doc{}, sources: map[string]*okf.Doc{},
		supersededBy: map[string]string{}, versions: map[string][]*okf.Doc{},
		strong: map[string]map[string]bool{}, weak: map[string]map[string]bool{},
		loadErrs: errs,
	}
	for _, d := range docs {
		sn.byID[d.ID] = d
		switch d.Front.Type {
		case "rule", "skill", "procedure":
			sn.items = append(sn.items, d)
			base, _ := okf.SplitVersion(d.ID)
			sn.versions[base] = append(sn.versions[base], d)
			if d.Front.Supersedes != "" {
				sn.supersededBy[d.Front.Supersedes] = d.ID
			}
			idTerms := text.Terms(strings.NewReplacer(":", " ", "/", " ", "@", " ").Replace(d.ID))
			sn.strong[d.ID] = text.Set(text.Terms(d.Front.Title), text.Terms(strings.Join(d.Front.Tags, " ")), idTerms)
			sn.weak[d.ID] = text.Set(text.Terms(d.Front.Description), text.Terms(d.Body))
		case "component":
			sn.components = append(sn.components, d)
		case "source":
			sn.sources[d.ID] = d
		case "conflict":
			sn.conflicts = append(sn.conflicts, d)
		}
	}
	for base := range sn.versions {
		v := sn.versions[base]
		sort.Slice(v, func(i, j int) bool {
			_, a := okf.SplitVersion(v[i].ID)
			_, b := okf.SplitVersion(v[j].ID)
			return a < b
		})
	}
	sn.chunks = buildChunks(loreDir, sn.sources)
	sn.hash = hashBundle(loreDir)
	return sn
}

func hashBundle(loreDir string) string {
	h := sha256.New()
	for _, dir := range okf.TypeDirs {
		_ = filepath.WalkDir(filepath.Join(loreDir, dir), func(p string, d fs.DirEntry, err error) error {
			if err != nil || d.IsDir() {
				return nil
			}
			rel, _ := filepath.Rel(loreDir, p)
			h.Write([]byte(filepath.ToSlash(rel)))
			if data, err := os.ReadFile(p); err == nil {
				h.Write(data)
			}
			return nil
		})
	}
	return "sha256:" + hex.EncodeToString(h.Sum(nil))[:16]
}

// constants returns the thresholds recorded with every result.
func (s *FileStore) constants() result.Constants {
	return result.Constants{
		AbstainBand:     s.cfg.AbstainBand,
		ConflictMinConf: s.cfg.ConflictMinConfidence,
		TokenBudget:     s.cfg.TokenBudget,
		ConfidenceMode:  "deterministic",
	}
}

// watch reloads the snapshot when knowledge files change, debounced.
func (s *FileStore) watch() error {
	w, err := fsnotify.NewWatcher()
	if err != nil {
		return err
	}
	s.watcher = w
	addTree := func(dir string) {
		_ = filepath.WalkDir(dir, func(p string, d fs.DirEntry, err error) error {
			if err == nil && d.IsDir() && !s.ignored(p) {
				_ = w.Add(p)
			}
			return nil
		})
	}
	addTree(s.loreDir)
	go func() {
		var timer *time.Timer
		fire := make(chan struct{}, 1)
		for {
			select {
			case <-s.done:
				return
			case ev, ok := <-w.Events:
				if !ok {
					return
				}
				if s.ignored(ev.Name) {
					continue
				}
				if ev.Has(fsnotify.Create) {
					if st, err := os.Stat(ev.Name); err == nil && st.IsDir() {
						addTree(ev.Name)
					}
				}
				if timer != nil {
					timer.Stop()
				}
				timer = time.AfterFunc(300*time.Millisecond, func() {
					select {
					case fire <- struct{}{}:
					default:
					}
				})
			case <-fire:
				_ = s.Reload()
			case err, ok := <-w.Errors:
				if !ok {
					return
				}
				s.log.Warn("watch error", "err", err)
			}
		}
	}()
	return nil
}

// ignored filters runtime files Lore writes itself so they do not trigger reloads.
func (s *FileStore) ignored(p string) bool {
	rel, err := filepath.Rel(s.loreDir, p)
	if err != nil {
		return true
	}
	rel = filepath.ToSlash(rel)
	switch {
	case rel == "audit.log", rel == "decisions", strings.HasPrefix(rel, "decisions/"):
		return true
	case rel == "_staging/jobs", strings.HasPrefix(rel, "_staging/jobs/"), rel == "_staging/idempotency.json":
		return true
	}
	return false
}
