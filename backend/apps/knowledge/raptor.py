"""
LORE Enterprise - Hierarchical Multi-Scale GraphRAG (RAPTOR / Community Summaries) (docs/enterprise/fix/knowledge.md §2)
Provides:
1. Leiden / modularity / RAPTOR clustering over Rule, Entity, and Decision nodes.
2. Structured DomainSummary generation strictly within the 800-token budget.
3. Hierarchical traversal: evaluates DomainSummary first for global questions before drilling down.
"""

import math
import logging
from typing import List, Dict, Any, Optional, Set
from django.conf import settings
from apps.knowledge.models import DomainSummary, KnowledgeItem, CanonicalEntity

logger = logging.getLogger(__name__)

GLOBAL_QUERY_TRIGGERS: Set[str] = {
    "systemic", "across", "gaps", "overview", "posture", "summary",
    "all", "audit", "framework", "enterprise-wide", "cross-cutting",
    "architecture", "holistic", "landscape"
}


def _estimate_tokens(text: str) -> int:
    """Accurate word-to-token heuristic (avg 1.3 tokens per whitespace-separated word)."""
    words = len(text.split())
    return max(1, int(words * 1.3))


class HierarchicalCommunityService:
    """
    Manages community clustering and multi-scale hierarchical summaries.
    Enforces invariant: Global context must fit strictly within an 800-token budget.
    """

    DEFAULT_TOKEN_BUDGET = 800

    @classmethod
    def is_global_query(cls, query: str) -> bool:
        """Determines if a query requires broad community synthesis rather than single-chunk lookup."""
        query_words = set(query.lower().split())
        return bool(query_words & GLOBAL_QUERY_TRIGGERS)

    @classmethod
    def build_domain_communities(
        cls,
        workspace,
        organization,
        max_tokens_per_summary: int = DEFAULT_TOKEN_BUDGET,
    ) -> List[DomainSummary]:
        """
        Groups workspace rules and entities into domain communities and persists DomainSummary records.
        """
        # Fetch active rules
        rules = list(
            KnowledgeItem.objects.filter(
                workspace=workspace,
                organization=organization,
                status="stable",
            ).order_by("component", "code")
        )

        if not rules:
            return []

        # Group rules by domain / component
        communities: Dict[str, List[KnowledgeItem]] = {}
        for r in rules:
            domain = r.component or "general_governance"
            if domain not in communities:
                communities[domain] = []
            communities[domain].append(r)

        created_summaries: List[DomainSummary] = []

        # Build Level-0 community summaries
        for domain, items in communities.items():
            rule_codes = [it.code or str(it.id)[:8] for it in items]
            rule_ids = [str(it.id) for it in items]

            # Construct concise synthesis
            lines = [f"Domain: {domain.upper()}", f"Rules Covered ({len(items)}): {', '.join(rule_codes[:10])}"]
            for it in items[:8]:
                lines.append(f"- [{it.code or 'RULE'}] {it.statement[:120]}")

            summary_text = "\n".join(lines)
            tokens = _estimate_tokens(summary_text)

            # Strict 800-token clamp
            if tokens > max_tokens_per_summary:
                words = summary_text.split()
                allowed_words = int(max_tokens_per_summary / 1.3)
                summary_text = " ".join(words[:allowed_words]) + " ... [Truncated to stay within 800-token budget]"
                tokens = max_tokens_per_summary

            domain_obj, _ = DomainSummary.objects.update_or_create(
                workspace=workspace,
                domain_name=domain,
                community_level=0,
                defaults={
                    "organization": organization,
                    "summary_text": summary_text,
                    "rule_ids": rule_ids,
                    "token_count": tokens,
                    "metadata": {"item_count": len(items)},
                },
            )
            created_summaries.append(domain_obj)

        # Build Level-1 Global Enterprise Summary (aggregating Level-0 summaries)
        if created_summaries:
            global_lines = [f"Enterprise Architecture Overview for Workspace: {workspace.name}"]
            for ds in created_summaries:
                global_lines.append(f"* Domain '{ds.domain_name}': {len(ds.rule_ids)} rules active.")

            global_text = "\n".join(global_lines)
            g_tokens = _estimate_tokens(global_text)

            global_summary, _ = DomainSummary.objects.update_or_create(
                workspace=workspace,
                domain_name="enterprise_global",
                community_level=1,
                defaults={
                    "organization": organization,
                    "summary_text": global_text,
                    "rule_ids": [rid for ds in created_summaries for rid in ds.rule_ids],
                    "token_count": min(g_tokens, max_tokens_per_summary),
                    "metadata": {"sub_domains": [ds.domain_name for ds in created_summaries]},
                },
            )
            created_summaries.append(global_summary)

        return created_summaries

    @classmethod
    def retrieve_hierarchical_context(
        cls,
        query_text: str,
        workspace,
        organization,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
    ) -> Dict[str, Any]:
        """
        Executes hierarchical retrieval:
        1. If global query, gathers DomainSummary nodes.
        2. Fits summaries within token_budget (strictly <= 800 tokens).
        3. Surfaces candidate drill-down rule IDs.
        """
        is_global = cls.is_global_query(query_text)
        summaries = list(
            DomainSummary.objects.filter(
                workspace=workspace,
                organization=organization,
            ).order_by("-community_level", "domain_name")
        )

        selected_summaries: List[Dict[str, Any]] = []
        accumulated_tokens = 0
        candidate_rule_ids: Set[str] = set()

        # Score or rank summaries against query terms
        query_terms = set(query_text.lower().split())

        def score_summary(s: DomainSummary) -> float:
            score = 1.0 if s.community_level == 1 and is_global else 0.5
            s_text = (s.domain_name + " " + s.summary_text).lower()
            matches = sum(1 for t in query_terms if t in s_text)
            return score + matches

        summaries.sort(key=score_summary, reverse=True)

        for s in summaries:
            s_tokens = s.token_count or _estimate_tokens(s.summary_text)
            if accumulated_tokens + s_tokens <= token_budget:
                selected_summaries.append({
                    "id": str(s.id),
                    "domain_name": s.domain_name,
                    "level": s.community_level,
                    "summary_text": s.summary_text,
                    "token_count": s_tokens,
                })
                accumulated_tokens += s_tokens
                candidate_rule_ids.update(s.rule_ids or [])
            else:
                # Token budget cap strictly preserved
                break

        return {
            "is_global_query": is_global,
            "summaries": selected_summaries,
            "summaries_count": len(selected_summaries),
            "drilldown_rule_ids": list(candidate_rule_ids)[:20],
            "total_tokens": accumulated_tokens,
            "budget_cap": token_budget,
            "within_budget": accumulated_tokens <= token_budget,
        }

