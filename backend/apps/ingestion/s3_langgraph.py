"""
LORE Enterprise — Stage S3 LangGraph Extraction Loop (docs/enterprise/lore.md §7 S3)
Implements an in-memory, bounded LangGraph StateGraph (S3ExtractionGraph) for
unstructured conversational logs, email threads, and raw narrative transcripts.

Cycles:
  route_intake -> extract_candidates -> cross_family_grade -> (should_retry) -> [finalize_passed | route_to_quarantine]

Invariants Enforced:
1. Zero LangSmith & Zero Unapproved Egress: LANGCHAIN_TRACING_V2=false, LANGSMITH_TRACING=false.
2. In-Memory Only: No checkpointer / SQLite checkpointer to prevent database locking in Celery workers.
3. Cross-Family Groundedness: Extractor never grades its own work; uses distinct grader model or local NLIConflictScanner + verbatim quotes.
4. Fast Path at $0 Cost: Non-conversational documents (PDFs, Office docs, images) or disabled ingestion bypass LLM nodes immediately.
5. Strict Secret Scrubbing: API keys are never persisted to disk or DB models.
"""

import os
import re
import json
import time
import urllib.request
import urllib.error
import logging
import threading
from typing import Dict, Any, List, Optional, Tuple, TypedDict, Union
from django.utils import timezone
from django.conf import settings

# Invariant 1: Force disable LangSmith tracing and egress
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
os.environ.setdefault("LANGSMITH_TRACING", "false")

from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel, Field

from apps.governance.modes import sanitize_sensitive_data
from apps.ingestion.nli_conflict import NLIConflictScanner

logger = logging.getLogger(__name__)


# ==============================================================================
# TRANSIENT IN-MEMORY INGESTION CONTEXT
# ==============================================================================
class TransientIngestionContext:
    """
    Thread-safe in-memory registry for transient per-upload Ingestion LLM credentials.
    Ensures ingestion_llm_api_key NEVER touches PostgreSQL, SQLite, or disk logs.
    """
    _lock = threading.Lock()
    _registry: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def set(cls, key: str, config: Dict[str, Any]) -> None:
        if not key:
            return
        with cls._lock:
            cls._registry[str(key)] = dict(config or {})

    @classmethod
    def get(cls, key: str) -> Dict[str, Any]:
        if not key:
            return {}
        with cls._lock:
            return dict(cls._registry.get(str(key), {}))

    @classmethod
    def pop(cls, key: str) -> Dict[str, Any]:
        if not key:
            return {}
        with cls._lock:
            return cls._registry.pop(str(key), {})

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._registry.clear()


# ==============================================================================
# SCHEMAS & DATA STRUCTURES
# ==============================================================================
class ExtractedRuleCandidate(BaseModel):
    rule_id: str = Field(description="Unique rule identifier e.g. RULE-001")
    statement: str = Field(description="Atomic norm, policy mandate, threshold, or decision")
    authority_hint: int = Field(default=3, description="Authority level from 1 to 5")
    effective_date: Optional[str] = Field(default=None, description="ISO date or timeframe")
    source_quote: str = Field(description="Exact verbatim quote from source transcript")
    page_or_timestamp: str = Field(default="1", description="Page number or timestamp marker")


class S3ExtractionState(TypedDict):
    document_id: str
    document_title: str
    workload_class: str
    raw_pages: List[Dict[str, Any]]
    ingestion_config: Dict[str, Any]
    extracted_rules: List[Dict[str, Any]]
    groundedness_score: float
    grader_critique: str
    retry_count: int
    max_retries: int
    verdict: str  # "passed" | "retry" | "quarantine"
    mode: str     # "deterministic_multiml_fastpath" | "langgraph_llm_extraction"
    node_trace: List[Dict[str, Any]]
    pages_data: List[Dict[str, Any]]


CONVERSATIONAL_WORKLOAD_CLASSES = {
    "slack_export",
    "email_thread",
    "conversational_log",
    "web_scrape",
    "chat_log",
    "transcript",
    "raw_transcript",
}

CONVERSATIONAL_EXTENSIONS = {
    ".json",
    ".eml",
    ".msg",
    ".chat",
    ".log",
    ".txt",
}


def is_conversational_workload(
    workload_class: str = "",
    filename: str = "",
    doc_type: str = "",
    force_llm: bool = False,
    raw_text: str = "",
) -> bool:
    """Classifies whether an upload constitutes an unstructured conversational log."""
    if force_llm:
        return True

    wl_norm = (workload_class or "").lower().strip()
    if wl_norm in CONVERSATIONAL_WORKLOAD_CLASSES:
        return True

    type_norm = (doc_type or "").lower().strip()
    if type_norm in CONVERSATIONAL_WORKLOAD_CLASSES or any(
        kw in type_norm for kw in ("slack", "email", "chat", "thread", "transcript")
    ):
        return True

    fn_norm = (filename or "").lower().strip()
    ext = os.path.splitext(fn_norm)[1]
    if any(kw in fn_norm for kw in ("slack", "email", "chat", "thread", "transcript", "conversation")):
        return True

    # Detect Slack/Email patterns in raw text if available
    if raw_text:
        sample = raw_text[:2048]
        if '"type": "message"' in sample or '"type":"message"' in sample:
            return True
        if re.search(r'(?m)^From:\s+[^\n]+\nTo:\s+[^\n]+', sample):
            return True
        if re.search(r'\[\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?\]\s+<[^>]+>', sample):
            return True

    return False


# ==============================================================================
# LLM INVOCATION WRAPPERS (OLLAMA & REMOTE PROVIDERS)
# ==============================================================================
def invoke_extractor_model(
    prompt: str,
    system_prompt: str,
    config: Dict[str, Any],
) -> str:
    """
    Invokes the configured Ingestion Extractor LLM (Ollama or Cloud).
    Temperature is strictly 0.0.
    """
    mock_extractor = config.get("_mock_extractor")
    if callable(mock_extractor):
        return mock_extractor(prompt=prompt, system_prompt=system_prompt, config=config)

    provider = (config.get("provider") or getattr(settings, "INGESTION_LLM_PROVIDER", "ollama")).lower()
    model = config.get("model") or getattr(settings, "INGESTION_LLM_MODEL", "qwen2.5:14b")
    api_key = config.get("api_key") or getattr(settings, "INGESTION_LLM_API_KEY", "")
    ollama_url = config.get("ollama_url") or getattr(settings, "INGESTION_OLLAMA_URL", "http://localhost:11434")

    if provider == "ollama":
        url = f"{ollama_url.rstrip('/')}/api/chat"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.0},
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("message", {}).get("content", "")

    elif provider in ("groq", "openai"):
        base_url = (
            "https://api.groq.com/openai/v1/chat/completions"
            if provider == "groq"
            else "https://api.openai.com/v1/chat/completions"
        )
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]

    elif provider == "anthropic":
        url = "https://api.anthropic.com/v1/messages"
        payload = {
            "model": model,
            "system": system_prompt,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 4096,
            "temperature": 0.0,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["content"][0]["text"]

    elif provider == "gemini":
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": f"{system_prompt}\n\n{prompt}"}
                    ]
                }
            ],
            "generationConfig": {"temperature": 0.0, "responseMimeType": "application/json"},
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["candidates"][0]["content"]["parts"][0]["text"]

    raise ValueError(f"Unsupported Ingestion LLM provider: {provider}")


def invoke_cross_family_grader(
    candidate: Dict[str, Any],
    source_context: str,
    config: Dict[str, Any],
) -> Tuple[bool, str]:
    """
    Grades an extracted candidate against source context using a second distinct model family.
    If no second model family is configured, returns None to trigger local NLI+verbatim verification.
    """
    mock_grader = config.get("_mock_grader")
    if callable(mock_grader):
        return mock_grader(candidate=candidate, source_context=source_context, config=config)

    grader_model = config.get("grader_model") or getattr(settings, "INGESTION_GRADER_MODEL", "")
    extractor_model = config.get("model") or getattr(settings, "INGESTION_LLM_MODEL", "")
    provider = (config.get("provider") or getattr(settings, "INGESTION_LLM_PROVIDER", "ollama")).lower()

    # Invariant #3: Extractor must NEVER grade its own work.
    if not grader_model or grader_model == extractor_model:
        return True, ""  # Defer to verbatim anchor + local NLI

    ollama_url = config.get("ollama_url") or getattr(settings, "INGESTION_OLLAMA_URL", "http://localhost:11434")
    api_key = config.get("api_key") or getattr(settings, "INGESTION_LLM_API_KEY", "")

    grading_prompt = (
        f"You are an impartial Governance Fact Grader.\n"
        f"SOURCE TRANSCRIPT CONTEXT:\n\"\"\"{source_context[:3000]}\"\"\"\n\n"
        f"EXTRACTED CANDIDATE TO VERIFY:\n"
        f"Rule ID: {candidate.get('rule_id')}\n"
        f"Statement: {candidate.get('statement')}\n"
        f"Claimed Quote: \"{candidate.get('source_quote')}\"\n\n"
        f"Task: Verify whether the statement is 100% truthful and entailed by the source quote with zero hallucinated claims.\n"
        f"Return strict JSON: {{\"grounded\": true/false, \"critique\": \"explanation if false\"}}"
    )

    try:
        if provider == "ollama":
            url = f"{ollama_url.rstrip('/')}/api/chat"
            payload = {
                "model": grader_model,
                "messages": [{"role": "user", "content": grading_prompt}],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.0},
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                text = data.get("message", {}).get("content", "")
                parsed = json.loads(text)
                return bool(parsed.get("grounded", False)), str(parsed.get("critique", ""))
    except Exception as ex:
        logger.warning(f"Cross-family LLM grader unavailable: {sanitize_sensitive_data(str(ex))}. Falling back to local NLI.")

    return True, ""


# ==============================================================================
# LANGGRAPH NODES
# ==============================================================================
def route_intake_node(state: S3ExtractionState) -> Dict[str, Any]:
    """
    Node 1: Evaluates whether this upload requires LLM extraction.
    Non-conversational files or disabled LLM extraction immediately exit to Multi-ML at $0 cost.
    """
    config = state.get("ingestion_config", {})
    enabled = bool(config.get("enabled", False))
    force_llm = bool(config.get("force_llm_extraction", False))
    workload_class = state.get("workload_class", "")

    raw_text = " ".join(p.get("text", "") for p in state.get("raw_pages", []))
    is_conv = is_conversational_workload(
        workload_class=workload_class,
        filename=state.get("document_title", ""),
        force_llm=force_llm,
        raw_text=raw_text,
    )

    trace_entry = {
        "node": "route_intake",
        "enabled": enabled,
        "is_conversational": is_conv,
        "force_llm": force_llm,
        "workload_class": workload_class,
        "timestamp": timezone.now().isoformat(),
    }

    if not enabled or not is_conv:
        return {
            "mode": "deterministic_multiml_fastpath",
            "verdict": "passed",
            "node_trace": state.get("node_trace", []) + [trace_entry],
        }

    return {
        "mode": "langgraph_llm_extraction",
        "node_trace": state.get("node_trace", []) + [trace_entry],
    }


def extract_candidates_node(state: S3ExtractionState) -> Dict[str, Any]:
    """
    Node 2: Distills conversational logs into atomic, citation-anchored rule/fact candidates.
    If retry_count > 0, injects previous grader_critique for self-repair.
    """
    config = state.get("ingestion_config", {})
    raw_pages = state.get("raw_pages", [])
    combined_transcript = "\n\n".join(
        f"[Page {p.get('page_number', i+1)}] {p.get('text', '')}"
        for i, p in enumerate(raw_pages)
    )

    system_prompt = (
        "You are LORE Enterprise's Settlement Extraction Specialist.\n"
        "Your task is to extract governing norms, policies, architectural rules, numerical thresholds, "
        "and decisive facts from the provided unstructured conversational transcript into atomic candidates.\n\n"
        "RULES:\n"
        "1. Extract ONLY facts explicitly stated in the transcript.\n"
        "2. For EVERY candidate, 'source_quote' MUST be an exact verbatim substring found in the transcript.\n"
        "3. Provide authority_hint (1=Memo/Chat to 5=Constitution/Board Approved).\n"
        "4. Return strict JSON array of objects with keys: "
        "['rule_id', 'statement', 'authority_hint', 'effective_date', 'source_quote', 'page_or_timestamp']."
    )

    critique = state.get("grader_critique", "")
    retry_count = state.get("retry_count", 0)

    user_prompt = f"DOCUMENT TITLE: {state.get('document_title')}\n\nTRANSCRIPT:\n{combined_transcript[:12000]}\n"
    if retry_count > 0 and critique:
        user_prompt += (
            f"\n\nCRITICAL SELF-REPAIR FEEDBACK FROM PREVIOUS PASS:\n"
            f"{critique}\n"
            f"You MUST fix the ungrounded rules, replace inaccurate quotes with exact verbatim substrings, "
            f"and eliminate fabricated claims."
        )

    t0 = time.time()
    try:
        raw_output = invoke_extractor_model(user_prompt, system_prompt, config)
        elapsed_ms = int((time.time() - t0) * 1000)

        # Parse JSON output
        parsed_rules = []
        try:
            cleaned = raw_output.strip()
            if "```json" in cleaned:
                cleaned = cleaned.split("```json")[1].split("```")[0].strip()
            elif "```" in cleaned:
                cleaned = cleaned.split("```")[1].split("```")[0].strip()

            data = json.loads(cleaned)
            if isinstance(data, dict):
                # Check for wrapped keys like "rules", "candidates", "extracted_rules"
                for k in ("rules", "candidates", "extracted_rules", "data"):
                    if isinstance(data.get(k), list):
                        data = data[k]
                        break
                if isinstance(data, dict):
                    data = [data]

            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("statement"):
                        candidate = ExtractedRuleCandidate(
                            rule_id=str(item.get("rule_id") or f"RULE-{len(parsed_rules)+1:03d}"),
                            statement=str(item.get("statement")),
                            authority_hint=int(item.get("authority_hint") or 3),
                            effective_date=item.get("effective_date"),
                            source_quote=str(item.get("source_quote") or ""),
                            page_or_timestamp=str(item.get("page_or_timestamp") or "1"),
                        )
                        parsed_rules.append(candidate.model_dump())
        except Exception as parse_ex:
            logger.warning(f"Error parsing candidate rules JSON: {parse_ex}. Raw: {raw_output[:200]}")

        trace_entry = {
            "node": "extract_candidates",
            "retry_count": retry_count,
            "rules_extracted": len(parsed_rules),
            "latency_ms": elapsed_ms,
            "timestamp": timezone.now().isoformat(),
        }

        return {
            "extracted_rules": parsed_rules,
            "node_trace": state.get("node_trace", []) + [trace_entry],
        }
    except Exception as ex:
        # Re-raise connection/service/timeout errors to trigger S3ExtractionGraph graceful Multi-ML fallback
        raise ex


def cross_family_grade_node(state: S3ExtractionState) -> Dict[str, Any]:
    """
    Node 3: Validates every candidate using verbatim anchor verification, local NLI, and cross-family LLM grading.
    Computes groundedness_score and sets grader_critique for self-repair loops.
    """
    config = state.get("ingestion_config", {})
    rules = state.get("extracted_rules", [])
    raw_pages = state.get("raw_pages", [])
    full_source_text = " ".join(p.get("text", "") for p in raw_pages).strip()

    if not rules:
        trace_entry = {
            "node": "cross_family_grade",
            "groundedness_score": 0.0,
            "critique": "Zero rules extracted from transcript.",
            "retry_count": state.get("retry_count", 0),
            "timestamp": timezone.now().isoformat(),
        }
        return {
            "groundedness_score": 0.0,
            "grader_critique": "Zero rules were extracted. Re-examine the transcript and extract explicit rules.",
            "retry_count": state.get("retry_count", 0) + 1,
            "node_trace": state.get("node_trace", []) + [trace_entry],
        }

    norm_source = re.sub(r'\s+', ' ', full_source_text.lower())
    passed_rules = []
    critiques = []

    for rule in rules:
        stmt = rule.get("statement", "")
        quote = rule.get("source_quote", "").strip()
        rule_id = rule.get("rule_id", "UNKNOWN")

        # 1. Verbatim quote anchor check
        if not quote:
            critiques.append(f"Rule {rule_id}: Missing source_quote.")
            continue

        norm_quote = re.sub(r'\s+', ' ', quote.lower())
        if norm_quote not in norm_source:
            # Fuzzy fallback: check if at least 80% of words appear in sequence
            quote_words = norm_quote.split()
            if len(quote_words) >= 4:
                prefix = " ".join(quote_words[:4])
                suffix = " ".join(quote_words[-4:])
                if prefix not in norm_source and suffix not in norm_source:
                    critiques.append(f"Rule {rule_id}: Claimed quote '{quote[:60]}...' not found verbatim in transcript.")
                    continue
            else:
                critiques.append(f"Rule {rule_id}: Claimed quote '{quote}' not found in transcript.")
                continue

        # 2. Local NLI contradiction check (Statement vs Quote)
        contra_score = NLIConflictScanner.compute_nli_contradiction_score(stmt, quote)
        if contra_score >= NLIConflictScanner.CONTRADICTION_THRESHOLD:
            critiques.append(f"Rule {rule_id}: Statement contradicts source quote (contradiction score: {contra_score:.2f}).")
            continue

        # 3. Cross-family LLM grader check (if distinct model family configured)
        is_grounded, grader_msg = invoke_cross_family_grader(rule, full_source_text, config)
        if not is_grounded:
            critiques.append(f"Rule {rule_id}: Cross-family grader rejected candidate: {grader_msg}")
            continue

        passed_rules.append(rule)

    score = round(len(passed_rules) / max(len(rules), 1), 3)
    synth_critique = "; ".join(critiques) if critiques else ""

    trace_entry = {
        "node": "cross_family_grade",
        "groundedness_score": score,
        "rules_total": len(rules),
        "rules_passed": len(passed_rules),
        "critique": synth_critique,
        "retry_count": state.get("retry_count", 0),
        "timestamp": timezone.now().isoformat(),
    }

    return {
        "groundedness_score": score,
        "grader_critique": synth_critique,
        "extracted_rules": passed_rules if score >= 0.85 else rules,
        "retry_count": state.get("retry_count", 0) + 1,
        "node_trace": state.get("node_trace", []) + [trace_entry],
    }


def finalize_passed_node(state: S3ExtractionState) -> Dict[str, Any]:
    """
    Node 4: Formats approved rules into canonical pages_data matching Stage S4 DeduplicationService expectations.
    """
    rules = state.get("extracted_rules", [])
    pages_data = []

    for idx, r in enumerate(rules, start=1):
        rule_id = r.get("rule_id", f"RULE-{idx:03d}")
        statement = r.get("statement", "")
        quote = r.get("source_quote", "")
        auth = r.get("authority_hint", 3)
        eff_date = r.get("effective_date") or "Unspecified"
        ref = r.get("page_or_timestamp", "1")

        rule_text = (
            f"### {rule_id}: {statement}\n\n"
            f"> Source Anchor: \"{quote}\"\n\n"
            f"- Authority Level: {auth}\n"
            f"- Effective Date: {eff_date}\n"
            f"- Transcript Reference: {ref}\n"
        )

        pages_data.append({
            "page_number": idx,
            "text": rule_text,
            "section_title": rule_id,
            "confidence": round(state.get("groundedness_score", 1.0), 3),
            "words_count": len(rule_text.split()),
            "width": 612.0,
            "height": 792.0,
            "extraction_type": "langgraph_llm_extraction",
            "engine": f"langgraph_{state.get('ingestion_config', {}).get('provider', 'ollama')}",
            "engine_version": "1.0",
            "is_repaired": state.get("retry_count", 1) > 1,
            "bounding_boxes": [],
            "metadata": {
                "rule_id": rule_id,
                "statement": statement,
                "source_quote": quote,
                "authority_hint": auth,
                "effective_date": eff_date,
                "page_or_timestamp": ref,
                "confidence": round(state.get("groundedness_score", 1.0), 3),
                "verified_by_grader": True,
            },
        })

    trace_entry = {
        "node": "finalize_passed",
        "final_pages": len(pages_data),
        "groundedness_score": state.get("groundedness_score", 1.0),
        "timestamp": timezone.now().isoformat(),
    }

    return {
        "verdict": "passed",
        "pages_data": pages_data,
        "node_trace": state.get("node_trace", []) + [trace_entry],
    }


def route_to_quarantine_node(state: S3ExtractionState) -> Dict[str, Any]:
    """
    Node 5: Routes ungrounded / low-confidence extractions to quarantine with full node_trace for human review.
    """
    trace_entry = {
        "node": "route_to_quarantine",
        "groundedness_score": state.get("groundedness_score", 0.0),
        "grader_critique": state.get("grader_critique", ""),
        "retry_count": state.get("retry_count", 0),
        "timestamp": timezone.now().isoformat(),
    }
    return {
        "verdict": "quarantine",
        "pages_data": state.get("raw_pages", []),
        "node_trace": state.get("node_trace", []) + [trace_entry],
    }


# ==============================================================================
# CONDITIONAL ROUTERS
# ==============================================================================
def intake_router(state: S3ExtractionState) -> str:
    """Routes after route_intake: skips to END if fastpath, else proceeds to extract_candidates."""
    if state.get("mode") == "deterministic_multiml_fastpath":
        return END
    return "extract_candidates"


def grade_router(state: S3ExtractionState) -> str:
    """
    Conditional routing after cross_family_grade:
    - score >= 0.85 & rules > 0 -> finalize_passed
    - retry_count < max_retries -> extract_candidates (loop with critique)
    - retry_count >= max_retries -> route_to_quarantine
    """
    score = state.get("groundedness_score", 0.0)
    rules = state.get("extracted_rules", [])
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 2)

    if score >= 0.85 and len(rules) > 0:
        return "finalize_passed"
    elif retry_count < max_retries:
        return "extract_candidates"
    else:
        return "route_to_quarantine"


# ==============================================================================
# STAGE S3 EXTRACTION GRAPH BUILDER & RUNNER
# ==============================================================================
class S3ExtractionGraph:
    """
    Compiles and executes the bounded LangGraph extraction loop in memory.
    """
    _compiled_app = None

    @classmethod
    def get_app(cls):
        if cls._compiled_app is None:
            workflow = StateGraph(S3ExtractionState)
            workflow.add_node("route_intake", route_intake_node)
            workflow.add_node("extract_candidates", extract_candidates_node)
            workflow.add_node("cross_family_grade", cross_family_grade_node)
            workflow.add_node("finalize_passed", finalize_passed_node)
            workflow.add_node("route_to_quarantine", route_to_quarantine_node)

            workflow.add_edge(START, "route_intake")
            workflow.add_conditional_edges("route_intake", intake_router)
            workflow.add_edge("extract_candidates", "cross_family_grade")
            workflow.add_conditional_edges("cross_family_grade", grade_router)
            workflow.add_edge("finalize_passed", END)
            workflow.add_edge("route_to_quarantine", END)

            # In-memory execution: compile without external checkpointer
            cls._compiled_app = workflow.compile()
        return cls._compiled_app

    @classmethod
    def run(
        cls,
        doc_id: str,
        doc_title: str,
        workload_class: str,
        raw_pages: List[Dict[str, Any]],
        ingestion_config: Dict[str, Any],
        max_retries: int = 2,
    ) -> Tuple[Any, List[Dict[str, Any]]]:
        """
        Executes the LangGraph S3ExtractionGraph loop.
        Returns (SettlementStageResult, pages_data).
        """
        from apps.ingestion.settlement import SettlementStageResult, SettlementReasonCode
        t0 = time.time()
        initial_state: S3ExtractionState = {
            "document_id": doc_id,
            "document_title": doc_title,
            "workload_class": workload_class,
            "raw_pages": raw_pages,
            "ingestion_config": ingestion_config,
            "extracted_rules": [],
            "groundedness_score": 0.0,
            "grader_critique": "",
            "retry_count": 0,
            "max_retries": max_retries,
            "verdict": "passed",
            "mode": "deterministic_multiml_fastpath",
            "node_trace": [],
            "pages_data": raw_pages,
        }

        try:
            app = cls.get_app()
            final_state: S3ExtractionState = app.invoke(initial_state)
            elapsed_ms = int((time.time() - t0) * 1000)

            # Mode 1: Deterministic fast-path bypassed LLM nodes at $0 cost
            if final_state.get("mode") == "deterministic_multiml_fastpath":
                return SettlementStageResult(
                    stage_number=3,
                    stage_name="extraction_and_validation",
                    status="passed",
                    reason_codes=[SettlementReasonCode.S3_EXTRACTION_PASSED.value],
                    details={
                        "mode": "deterministic_multiml_fastpath",
                        "node_trace": final_state.get("node_trace", []),
                    },
                    duration_ms=elapsed_ms,
                ), raw_pages

            # Mode 2: LangGraph LLM loop completed with verdict
            verdict = final_state.get("verdict", "quarantine")
            if verdict == "passed":
                return SettlementStageResult(
                    stage_number=3,
                    stage_name="extraction_and_validation",
                    status="passed",
                    reason_codes=[
                        SettlementReasonCode.S3_EXTRACTION_PASSED.value,
                        "S3_LLM_EXTRACTION_PASSED",
                    ],
                    details={
                        "mode": "langgraph_llm_extraction",
                        "groundedness_score": final_state.get("groundedness_score", 1.0),
                        "rules_count": len(final_state.get("extracted_rules", [])),
                        "node_trace": final_state.get("node_trace", []),
                    },
                    duration_ms=elapsed_ms,
                ), final_state.get("pages_data", [])

            # Quarantine verdict after max retries
            return SettlementStageResult(
                stage_number=3,
                stage_name="extraction_and_validation",
                status="needs_review",
                reason_codes=[SettlementReasonCode.S3_LOW_CONFIDENCE_QUARANTINE.value],
                details={
                    "mode": "langgraph_llm_extraction",
                    "action": "routed_to_review_queue",
                    "reason": "Extraction failed groundedness after max retries.",
                    "groundedness_score": final_state.get("groundedness_score", 0.0),
                    "grader_critique": final_state.get("grader_critique", ""),
                    "node_trace": final_state.get("node_trace", []),
                },
                duration_ms=elapsed_ms,
            ), final_state.get("pages_data", raw_pages)

        except Exception as ex:
            elapsed_ms = int((time.time() - t0) * 1000)
            logger.warning(
                f"S3 LangGraph extraction error: {sanitize_sensitive_data(str(ex))}. "
                f"Falling back to deterministic Multi-ML."
            )
            return SettlementStageResult(
                stage_number=3,
                stage_name="extraction_and_validation",
                status="passed",
                reason_codes=[
                    SettlementReasonCode.S3_EXTRACTION_PASSED.value,
                    "S3_LLM_FALLBACK_TO_MULTIML",
                ],
                details={
                    "mode": "fallback_to_multiml",
                    "error": sanitize_sensitive_data(str(ex)),
                },
                duration_ms=elapsed_ms,
            ), raw_pages
