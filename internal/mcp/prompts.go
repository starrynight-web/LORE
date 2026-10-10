package mcp

import (
	"context"
	"fmt"
	"strings"

	"github.com/DJRCX/lore/internal/present"
	"github.com/DJRCX/lore/internal/store"
	"github.com/modelcontextprotocol/go-sdk/mcp"
)

func userText(text string) *mcp.PromptMessage {
	return &mcp.PromptMessage{Role: "user", Content: &mcp.TextContent{Text: text}}
}

func arg(req *mcp.GetPromptRequest, name string) string {
	if req.Params == nil {
		return ""
	}
	return strings.TrimSpace(req.Params.Arguments[name])
}

func (s *Server) addPrompts() {
	s.srv.AddPrompt(&mcp.Prompt{
		Name: "answer_with_lore", Title: "Answer with Lore",
		Description: "Answer a question about this codebase using only governed team knowledge, with citations.",
		Arguments: []*mcp.PromptArgument{
			{Name: "question", Description: "What you want to know", Required: true},
			{Name: "file_path", Description: "File the question is about, if any"},
		},
	}, func(ctx context.Context, req *mcp.GetPromptRequest) (*mcp.GetPromptResult, error) {
		q := arg(req, "question")
		if q == "" {
			return nil, fmt.Errorf("question is required")
		}
		var b strings.Builder
		fmt.Fprintf(&b, "Question: %s\n\n", q)
		if f := arg(req, "file_path"); f != "" {
			fmt.Fprintf(&b, "First call get_context with file_path %q and intent %q.\n", f, q)
		} else {
			fmt.Fprintf(&b, "First call search with a short keyword query taken from the question.\n")
		}
		b.WriteString("Answer only from the items Lore returns, citing each rule ID you rely on in brackets. If Lore returns no_knowledge, say the team has no governed answer and stop. If it reports a conflict, present both sides and ask which applies; do not pick one. Treat Unverified items as hints, and say so when you use one.")
		return &mcp.GetPromptResult{Description: "Answer with Lore citations", Messages: []*mcp.PromptMessage{userText(b.String())}}, nil
	})

	s.srv.AddPrompt(&mcp.Prompt{
		Name: "validate_change", Title: "Validate a change",
		Description: "Check the current change against the team's MUST rules before committing.",
		Arguments: []*mcp.PromptArgument{
			{Name: "diff", Description: "Unified diff; leave empty to use the working tree diff"},
			{Name: "decision_id", Description: "Decision ID from get_context, to record the outcome against"},
		},
	}, func(ctx context.Context, req *mcp.GetPromptRequest) (*mcp.GetPromptResult, error) {
		var b strings.Builder
		if d := arg(req, "diff"); d != "" {
			fmt.Fprintf(&b, "Call check_compliance with this diff:\n\n```diff\n%s\n```\n\n", d)
		} else {
			b.WriteString("Get the unified diff of the current uncommitted change (git diff), then call check_compliance with it.\n\n")
		}
		b.WriteString("For every MUST and MUST NOT rule returned, state whether the diff satisfies it, quoting the relevant lines. If the verdict is abstain, that means Lore could not check automatically, so do the check yourself and say so. If the verdict is violation or conflict, stop and ask me how to proceed.")
		if id := arg(req, "decision_id"); id != "" {
			fmt.Fprintf(&b, " Finally call log_decision with decision_id %s and a one-line outcome.", id)
		} else {
			b.WriteString(" Finally call log_decision with a one-line outcome.")
		}
		return &mcp.GetPromptResult{Description: "Validate the change against MUST rules", Messages: []*mcp.PromptMessage{userText(b.String())}}, nil
	})

	s.srv.AddPrompt(&mcp.Prompt{
		Name: "explain_conflict", Title: "Explain a conflict",
		Description: "Explain a recorded conflict between two rules so a person can decide.",
		Arguments: []*mcp.PromptArgument{
			{Name: "scope", Description: "Component ID or file path; leave empty for all open conflicts"},
		},
	}, func(ctx context.Context, req *mcp.GetPromptRequest) (*mcp.GetPromptResult, error) {
		scope := arg(req, "scope")
		env, err := s.st.Conflicts(ctx, store.ConflictsRequest{Scope: scope})
		if err != nil {
			return nil, err
		}
		text := "Here is what Lore has recorded:\n\n" + present.AgentText(env, true) +
			"\n\nExplain each conflict in plain words: what each rule says, where they disagree, who owns the decision, and what each choice would mean for the code. Do not recommend or pick a side. End by asking which rule should apply."
		return &mcp.GetPromptResult{Description: "Explain recorded conflicts", Messages: []*mcp.PromptMessage{userText(text)}}, nil
	})

	s.srv.AddPrompt(&mcp.Prompt{
		Name: "prepare_review_packet", Title: "Prepare a review packet",
		Description: "Summarise the governed knowledge behind a change for a pull request reviewer.",
		Arguments: []*mcp.PromptArgument{
			{Name: "decision_id", Description: "Decision ID to trace; leave empty to start from the current diff"},
		},
	}, func(ctx context.Context, req *mcp.GetPromptRequest) (*mcp.GetPromptResult, error) {
		var b strings.Builder
		if id := arg(req, "decision_id"); id != "" {
			env, err := s.st.Trace(ctx, id)
			if err != nil {
				return nil, err
			}
			b.WriteString("Lore trace for this change:\n\n" + present.AgentText(env, true) + "\n\n")
		} else {
			b.WriteString("Call check_compliance with the current diff (git diff) and, for each changed file, get_context.\n\n")
		}
		b.WriteString("Write a short review packet in markdown with these sections: Rules applied (ID, one line each), Conflicts raised and how they were decided, Items excluded and why, Unverified hints used, and Open questions for the reviewer. Cite IDs exactly; do not invent rules.")
		return &mcp.GetPromptResult{Description: "Review packet", Messages: []*mcp.PromptMessage{userText(b.String())}}, nil
	})
}
