package mcp

import (
	"context"
	"errors"

	"github.com/modelcontextprotocol/go-sdk/mcp"
	"github.com/starrynight-web/LORE/internal/store"
)

var templates = []*mcp.ResourceTemplate{
	{URITemplate: "lore://rules/{+id}", Name: "rule", Title: "Rule", Description: "A governed rule, e.g. lore://rules/auth/jwt-expiry@v3", MIMEType: "text/markdown"},
	{URITemplate: "lore://skills/{+id}", Name: "skill", Title: "Skill", Description: "Full text of a skill, e.g. lore://skills/go/error-wrapping@v2", MIMEType: "text/markdown"},
	{URITemplate: "lore://procedures/{+id}", Name: "procedure", Title: "Procedure", Description: "A procedure", MIMEType: "text/markdown"},
	{URITemplate: "lore://sources/{+id}", Name: "source", Title: "Source", Description: "A source record, or one staged file under it", MIMEType: "text/markdown"},
	{URITemplate: "lore://conflicts/{id}", Name: "conflict", Title: "Conflict", Description: "A recorded conflict between two rules", MIMEType: "text/markdown"},
	{URITemplate: "lore://decisions/{id}", Name: "decision", Title: "Decision", Description: "A decision record written by get_context or check_compliance", MIMEType: "text/markdown"},
	{URITemplate: "lore://schemas/{name}", Name: "schema", Title: "Schema", Description: "Published JSON Schemas", MIMEType: "application/json"},
}

func (s *Server) readResource(ctx context.Context, req *mcp.ReadResourceRequest) (*mcp.ReadResourceResult, error) {
	uri := req.Params.URI
	r, err := s.st.ReadResource(ctx, uri)
	if err != nil {
		var nf store.ErrNotFound
		if errors.As(err, &nf) {
			return nil, mcp.ResourceNotFoundError(uri)
		}
		return nil, err
	}
	return &mcp.ReadResourceResult{Contents: []*mcp.ResourceContents{{URI: uri, MIMEType: r.MIMEType, Text: r.Text}}}, nil
}

func (s *Server) addResourceTemplates() {
	for _, t := range templates {
		s.srv.AddResourceTemplate(t, s.readResource)
	}
}

// syncResources mirrors the store's resource list into the server, so clients
// with a resource picker can browse it. Templates cover anything not listed.
func (s *Server) syncResources() {
	list, err := s.st.ListResources(context.Background())
	if err != nil {
		s.opts.Logger.Warn("listing resources failed", "err", err)
		return
	}
	s.resMu.Lock()
	defer s.resMu.Unlock()
	next := make(map[string]bool, len(list))
	for _, r := range list {
		next[r.URI] = true
	}
	var gone []string
	for uri := range s.resource {
		if !next[uri] {
			gone = append(gone, uri)
		}
	}
	if len(gone) > 0 {
		s.srv.RemoveResources(gone...)
	}
	for _, r := range list {
		s.srv.AddResource(&mcp.Resource{URI: r.URI, Name: r.Name, Title: r.Title, Description: r.Description, MIMEType: r.MIMEType}, s.readResource)
	}
	s.resource = next
}
