#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hakims — Focused AI Automation Feature PoC (FastAPI + OpenAI Structured Output + Lightweight RAG + React UI)
=============================================================================================================
Scope covered in this single drop-in module:
1. Reference Document Grounding (RAG): Lightweight chunking + OpenAI Embeddings cosine similarity retrieval
   (zero heavy vector DB dependency required for small reference doc sets).
2. OpenAI API Workflow: Strict JSON Schema Structured Outputs (`response_format`) with automatic retry/backoff
   for `RateLimitError` (429) and `APITimeoutError`.
3. FastAPI Endpoint (`POST /api/ai-feature`): Pydantic request/response validation + clean HTTP error handling.
4. Lightweight React UI Component (included in docstring below) ready to drop into your frontend.
"""

import os
import math
import time
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from openai import OpenAI, APITimeoutError, RateLimitError, APIError

app = FastAPI(title="Hakims AI Automation & Grounded RAG Endpoint", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# 1. SMALL REFERENCE DOCUMENT STORE & LIGHTWEIGHT COSINE RAG RETRIEVER
# ---------------------------------------------------------------------------
REFERENCE_DOCS = [
    {
        "doc_id": "doc_onboarding_v2",
        "title": "Workspace Onboarding & Setup Guide",
        "content": "New workspaces initialize in 3 steps: configure API keys, select grounding docs, and enable webhook notifications.",
    },
    {
        "doc_id": "doc_api_limits",
        "title": "API Rate Limits & Error Recovery",
        "content": "Standard tier supports 60 requests per minute. Exceeding quota returns HTTP 429 with exponential backoff recommended.",
    },
    {
        "doc_id": "doc_security_sso",
        "title": "Team Role Permissions & Security",
        "content": "Admins can manage reference documents and review AI automation logs. Role-based access restricts billing settings.",
    },
]


def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a)) or 1.0
    norm_b = math.sqrt(sum(b * b for b in vec_b)) or 1.0
    return dot / (norm_a * norm_b)


def retrieve_relevant_chunks(client: OpenAI, query: str, top_k: int = 2) -> List[dict]:
    """Embeds user query and scores against reference document chunks."""
    texts = [query] + [d["content"] for d in REFERENCE_DOCS]
    emb_resp = client.embeddings.create(model="text-embedding-3-small", input=texts)
    query_vec = emb_resp.data[0].embedding

    scored = []
    for idx, doc in enumerate(REFERENCE_DOCS):
        doc_vec = emb_resp.data[idx + 1].embedding
        score = round(_cosine_similarity(query_vec, doc_vec), 3)
        if score >= 0.65:
            scored.append({**doc, "similarity_score": score})

    scored.sort(key=lambda x: x["similarity_score"], reverse=True)
    return scored[:top_k]


# ---------------------------------------------------------------------------
# 2. PYDANTIC CONTRACTS (STRUCTURED INPUT & OUTPUT)
# ---------------------------------------------------------------------------
class UserFeatureRequest(BaseModel):
    user_input: str = Field(..., min_length=3, max_length=2000, description="User prompt or workflow input")
    use_rag_grounding: bool = Field(default=True, description="Toggle RAG reference document grounding")


class StructuredAIOutput(BaseModel):
    summary_answer: str
    recommended_actions: List[str]
    citations: List[str]
    confidence_score: float
    grounded_in_docs: bool


class FeatureAPIResponse(BaseModel):
    status: str
    latency_ms: int
    retrieved_chunks: List[dict]
    result: StructuredAIOutput


# ---------------------------------------------------------------------------
# 3. FASTAPI ENDPOINT WITH OPENAI RETRY & ERROR HANDLING
# ---------------------------------------------------------------------------
def process_ai_automation(payload: UserFeatureRequest) -> FeatureAPIResponse:
    start_ts = time.time()
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=500, detail="Missing OPENAI_API_KEY environment variable.")

    client = OpenAI(api_key=api_key, timeout=20.0)

    # Step A: Optional RAG Grounding against small reference set
    matched_chunks = []
    context_block = "No external reference documents requested."
    if payload.use_rag_grounding:
        try:
            matched_chunks = retrieve_relevant_chunks(client, payload.user_input)
            if matched_chunks:
                context_block = "\n".join(
                    f"[{c['doc_id']}] ({c['title']}): {c['content']}" for c in matched_chunks
                )
            else:
                context_block = "No matching reference document passed the 0.65 similarity threshold."
        except Exception as exc:
            context_block = f"RAG fallback active (embedding warning: {type(exc).__name__})."

    # Step B: OpenAI Structured Output call with bounded retry for 429/Timeouts
    last_error: Optional[Exception] = None
    for attempt in range(3):
        try:
            completion = client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a focused AI workflow engine. Ground your answer strictly in the provided "
                            "Reference Context when available, cite matching doc_ids, and return structured JSON."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Reference Context:\n{context_block}\n\nUser Input:\n{payload.user_input}",
                    },
                ],
                response_format=StructuredAIOutput,
                temperature=0.2,
            )
            parsed_result: StructuredAIOutput = completion.choices[0].message.parsed
            elapsed_ms = int((time.time() - start_ts) * 1000)
            return FeatureAPIResponse(
                status="ok",
                latency_ms=elapsed_ms,
                retrieved_chunks=matched_chunks,
                result=parsed_result,
            )
        except (RateLimitError, APITimeoutError) as retry_err:
            last_error = retry_err
            time.sleep(0.8 * (attempt + 1))
        except APIError as api_err:
            raise HTTPException(status_code=502, detail=f"Upstream OpenAI API error: {api_err.message}")

    raise HTTPException(status_code=504, detail=f"LLM request failed after 3 retries: {type(last_error).__name__}")


app.add_api_route(
    "/api/ai-feature",
    process_ai_automation,
    methods=["POST"],
    response_model=FeatureAPIResponse,
)


# ---------------------------------------------------------------------------
# 4. LIGHTWEIGHT REACT COMPONENT (DROP-IN FRONTEND)
# ---------------------------------------------------------------------------
REACT_UI_COMPONENT_JSX = """
import React, { useState } from 'react';

export default function AIAutomationFeatureCard() {
  const [input, setInput] = useState('');
  const [useRag, setUseRag] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [data, setData] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!input.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/ai-feature', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_input: input, use_rag_grounding: useRag }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Request failed');
      setData(body);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ maxWidth: 640, padding: 20, border: '1px solid #e2e8f0', borderRadius: 12 }}>
      <h3>AI Workflow & Grounded RAG Assistant</h3>
      <form onSubmit={handleSubmit}>
        <textarea
          rows={3}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a workflow question or submit input for processing..."
          style={{ width: '100%', padding: 10, borderRadius: 8 }}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 10 }}>
          <label>
            <input type="checkbox" checked={useRag} onChange={(e) => setUseRag(e.target.checked)} />
            {' '}Ground in Reference Docs (RAG)
          </label>
          <button type="submit" disabled={loading}>
            {loading ? 'Processing...' : 'Run AI Workflow'}
          </button>
        </div>
      </form>

      {error && <div style={{ marginTop: 12, color: '#dc2626' }}>Error: {error}</div>}

      {data && (
        <div style={{ marginTop: 16, background: '#f8fafc', padding: 14, borderRadius: 8 }}>
          <p><strong>Answer:</strong> {data.result.summary_answer}</p>
          <p><strong>Action Items:</strong> {data.result.recommended_actions.join(' • ')}</p>
          <small>
            Citations: {data.result.citations.join(', ') || 'None'} |
            Confidence: {Math.round(data.result.confidence_score * 100)}% |
            Latency: {data.latency_ms}ms
          </small>
        </div>
      )}
    </div>
  );
}
"""
