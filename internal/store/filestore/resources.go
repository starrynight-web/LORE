package filestore

import (
	"context"
	"fmt"
	"os"
	"path"
	"path/filepath"
	"sort"
	"strings"

	"github.com/starrynight-web/LORE/internal/okf"
	"github.com/starrynight-web/LORE/internal/store"
	"github.com/starrynight-web/LORE/schemas"
)

const (
	mimeMarkdown            = "text/markdown"
	mimeJSON                = "application/json"
	recentDecisionResources = 20
)

func (s *FileStore) ListResources(ctx context.Context) ([]store.Resource, error) {
	sn := s.current()
	var out []store.Resource
	for _, d := range sn.items {
		out = append(out, store.Resource{
			URI: LinkFor(d.ID), Name: d.ID, Title: fmt.Sprintf("%s [%s]", firstNonEmpty(d.Front.Title, d.ID), firstNonEmpty(d.Front.Status, "draft")),
			Description: d.Text(), MIMEType: mimeMarkdown,
		})
	}
	for _, cd := range sn.conflicts {
		out = append(out, store.Resource{
			URI: LinkFor(cd.ID), Name: cd.ID, Title: firstNonEmpty(cd.Front.Title, cd.ID),
			Description: fmt.Sprintf("%s vs %s (%s)", cd.Front.LeftRule, cd.Front.RightRule, firstNonEmpty(cd.Front.Status, "open")),
			MIMEType:    mimeMarkdown,
		})
	}
	for _, src := range sn.sources {
		out = append(out, store.Resource{
			URI: LinkFor(src.ID), Name: src.ID, Title: firstNonEmpty(src.Front.Title, src.ID),
			Description: src.Front.Path, MIMEType: mimeMarkdown,
		})
	}
	ids := s.rec.List()
	if len(ids) > recentDecisionResources {
		ids = ids[:recentDecisionResources]
	}
	for _, id := range ids {
		out = append(out, store.Resource{URI: LinkFor(id), Name: id, Title: "Decision " + id, MIMEType: mimeMarkdown})
	}
	out = append(out, store.Resource{
		URI: "lore://schemas/lore.result.v1", Name: "lore.result.v1", Title: "lore.result/1 JSON Schema",
		Description: "Schema of every Lore read result", MIMEType: mimeJSON,
	})
	sort.Slice(out, func(i, j int) bool { return out[i].URI < out[j].URI })
	return out, nil
}

func (s *FileStore) ReadResource(ctx context.Context, uri string) (*store.Resource, error) {
	rest, ok := strings.CutPrefix(uri, "lore://")
	if !ok {
		return nil, store.ErrNotFound{What: uri}
	}
	kind, id, _ := strings.Cut(rest, "/")
	if id == "" || strings.Contains(id, "..") {
		return nil, store.ErrNotFound{What: uri}
	}
	sn := s.current()
	res := &store.Resource{URI: uri, Name: id, MIMEType: mimeMarkdown}
	switch kind {
	case "rules", "procedures":
		prefix := map[string]string{"rules": "rule:", "procedures": "procedure:"}[kind]
		d := sn.byID[prefix+id]
		if d == nil {
			return nil, store.ErrNotFound{What: uri}
		}
		return s.fileResource(res, d.Path)
	case "skills":
		d := sn.byID["skill:"+id]
		if d == nil {
			return nil, store.ErrNotFound{What: uri}
		}
		if src := sn.sources[d.Front.SourceID]; src != nil && src.Front.Staged != "" {
			if txt, err := s.readStaged(src, "SKILL.md"); err == nil {
				res.Title = firstNonEmpty(d.Front.Title, d.ID)
				res.Text = txt
				return res, nil
			}
		}
		return s.fileResource(res, d.Path)
	case "conflicts":
		for _, cd := range sn.conflicts {
			if cd.ID == id {
				return s.fileResource(res, cd.Path)
			}
		}
		return nil, store.ErrNotFound{What: uri}
	case "decisions":
		raw, err := s.rec.Raw(id)
		if err != nil {
			return nil, store.ErrNotFound{What: uri}
		}
		res.Text = string(raw)
		return res, nil
	case "sources":
		srcKey, file, _ := strings.Cut(id, "/")
		src := sn.sources["src:"+srcKey]
		if src == nil {
			return nil, store.ErrNotFound{What: uri}
		}
		if file == "" {
			r, err := s.fileResource(res, src.Path)
			if err != nil {
				return nil, err
			}
			if len(src.Front.Files) > 0 {
				var b strings.Builder
				b.WriteString("\n## Files\n")
				for _, f := range src.Front.Files {
					fmt.Fprintf(&b, "- lore://sources/%s/%s\n", srcKey, f)
				}
				r.Text += b.String()
			}
			return r, nil
		}
		txt, err := s.readStaged(src, file)
		if err != nil {
			return nil, store.ErrNotFound{What: uri}
		}
		res.Text = txt
		res.MIMEType = mimeFor(file)
		return res, nil
	case "schemas":
		if strings.TrimSuffix(id, ".json") == "lore.result.v1" {
			res.Text, res.MIMEType = string(schemas.ResultV1), mimeJSON
			return res, nil
		}
	}
	return nil, store.ErrNotFound{What: uri}
}

func (s *FileStore) fileResource(res *store.Resource, rel string) (*store.Resource, error) {
	data, err := os.ReadFile(filepath.Join(s.loreDir, filepath.FromSlash(rel)))
	if err != nil {
		return nil, store.ErrNotFound{What: res.URI}
	}
	res.Text = string(data)
	return res, nil
}

// readStaged reads a file from a source's staged folder, refusing paths that escape it.
func (s *FileStore) readStaged(src *okf.Doc, file string) (string, error) {
	clean := path.Clean("/" + filepath.ToSlash(file))[1:]
	if clean == "" || strings.HasPrefix(clean, "..") {
		return "", fmt.Errorf("invalid path %q", file)
	}
	base := filepath.Join(s.loreDir, filepath.FromSlash(src.Front.Staged))
	data, err := os.ReadFile(filepath.Join(base, filepath.FromSlash(clean)))
	if err != nil {
		return "", err
	}
	return string(data), nil
}

func mimeFor(file string) string {
	switch strings.ToLower(filepath.Ext(file)) {
	case ".md", ".markdown", ".mdx":
		return mimeMarkdown
	case ".json":
		return mimeJSON
	default:
		return "text/plain"
	}
}
