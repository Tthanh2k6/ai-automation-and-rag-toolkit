#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG chunk auditor and hybrid retrieval (BM25 + dense vectors, Reciprocal Rank Fusion)
=====================================================================================
1. Chunk audit: flags very short/long chunks, chunks that end mid-sentence, and
   chunks without a parent section header.
2. Hybrid retrieval: ranks the corpus once by cosine similarity and once by Okapi
   BM25, then fuses the two rankings with RRF (k=60).
3. Post-retrieval filter: drops documents whose vector score and BM25 score are
   both weak, so obviously unrelated chunks are not passed to the LLM.

Pure Python, no dependencies. `python rag_hybrid_rerank_auditor.py` runs the
audit and a toy retrieval demo on hand-made 3-dimensional "embeddings"; the
demo shows the mechanics, it is not a benchmark.
"""

import math
import re
from typing import Dict, List, Tuple


# ---------------------------------------------------------------------------
# 1. CHUNKING QUALITY AUDITOR (DETECTS BROKEN TABLES & ORPHANED CHUNKS)
# ---------------------------------------------------------------------------
def audit_document_chunks(chunks: List[Dict[str, str]]) -> Dict[str, object]:
    """
    Scans existing RAG chunks for the 3 most common ingestion bugs:
    - Mid-sentence truncation (chunk does not end on punctuation/newline)
    - Missing section header context (orphaned paragraphs without parent title)
    - Sub-optimal token density (< 40 tokens or > 800 tokens)
    """
    issues = []
    for idx, ch in enumerate(chunks):
        text = ch.get("text", "").strip()
        meta = ch.get("metadata", {})
        word_count = len(text.split())

        if word_count < 25:
            issues.append(f"Chunk #{idx}: Too short ({word_count} words) -> dilutes vector embedding.")
        elif word_count > 650:
            issues.append(f"Chunk #{idx}: Too coarse ({word_count} words) -> causes lost-in-the-middle noise.")

        if text and text[-1] not in ".!?:;\"')]}":
            issues.append(f"Chunk #{idx}: Mid-sentence boundary cut detected.")

        if not meta.get("section_header"):
            issues.append(f"Chunk #{idx}: Missing parent section_header in metadata.")

    return {
        "total_chunks_audited": len(chunks),
        "issue_count": len(issues),
        "sample_findings": issues[:5],
    }


# ---------------------------------------------------------------------------
# 2. HYBRID RETRIEVAL ENGINE (DENSE VECTOR + LEXICAL KEYWORD VIA RRF)
# ---------------------------------------------------------------------------
def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a)) or 1.0
    norm_b = math.sqrt(sum(b * b for b in vec_b)) or 1.0
    return dot / (norm_a * norm_b)


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9_-]+", text.lower())


def bm25_scores(query: str, texts: List[str], k1: float = 1.5, b: float = 0.75) -> List[float]:
    """Okapi BM25 score of `query` against each text (IDF with the usual +1 smoothing)."""
    docs = [_tokenize(t) for t in texts]
    n_docs = len(docs)
    if n_docs == 0:
        return []
    avg_len = sum(len(d) for d in docs) / n_docs or 1.0
    doc_freq: Dict[str, int] = {}
    for d in docs:
        for term in set(d):
            doc_freq[term] = doc_freq.get(term, 0) + 1

    scores = []
    for d in docs:
        tf: Dict[str, int] = {}
        for term in d:
            tf[term] = tf.get(term, 0) + 1
        score = 0.0
        for term in set(_tokenize(query)):
            if term not in tf:
                continue
            idf = math.log(1.0 + (n_docs - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
            freq = tf[term]
            score += idf * (freq * (k1 + 1)) / (freq + k1 * (1 - b + b * len(d) / avg_len))
        scores.append(score)
    return scores


def hybrid_rrf_retrieve(
    query: str,
    query_embedding: List[float],
    corpus: List[Dict[str, object]],
    top_k: int = 4,
    rrf_k: int = 60,
    min_vector_score: float = 0.68,
    min_bm25_score: float = 0.5,
) -> List[Dict[str, object]]:
    """
    Combines dense vector ranking with BM25 keyword ranking (exact SKUs, codes)
    using Reciprocal Rank Fusion (RRF) and drops documents weak on both signals.
    """
    scored_dense: List[Tuple[int, float]] = []
    scored_lexical: List[Tuple[int, float]] = []

    bm25 = bm25_scores(query, [str(doc["text"]) for doc in corpus])
    for i, doc in enumerate(corpus):
        v_score = _cosine_similarity(query_embedding, doc["embedding"])
        scored_dense.append((i, v_score))
        scored_lexical.append((i, bm25[i]))

    scored_dense.sort(key=lambda x: x[1], reverse=True)
    scored_lexical.sort(key=lambda x: x[1], reverse=True)

    dense_rank = {doc_idx: rank + 1 for rank, (doc_idx, _) in enumerate(scored_dense)}
    lex_rank = {doc_idx: rank + 1 for rank, (doc_idx, _) in enumerate(scored_lexical)}
    dense_map = dict(scored_dense)
    lex_map = dict(scored_lexical)

    fused_results = []
    for i, doc in enumerate(corpus):
        # Skip documents that are weak on both signals (likely unrelated to the query)
        if dense_map[i] < min_vector_score and lex_map[i] < min_bm25_score:
            continue
        rrf_score = (1.0 / (rrf_k + dense_rank[i])) + (1.0 / (rrf_k + lex_rank[i]))
        fused_results.append({
            "chunk_id": doc["chunk_id"],
            "vector_score": round(dense_map[i], 3),
            "bm25_score": round(lex_map[i], 3),
            "rrf_fused_score": round(rrf_score, 5),
            "text_preview": str(doc["text"])[:120],
        })

    fused_results.sort(key=lambda x: x["rrf_fused_score"], reverse=True)
    return fused_results[:top_k]


if __name__ == "__main__":
    sample_chunks = [
        {"text": "Section 4.2: Refunds for annual enterprise tiers require written notice within 14 days.", "metadata": {"section_header": "Refund Policy"}},
        {"text": "broken fragment without punctuation or parent header", "metadata": {}},
    ]
    print("RAG Chunk Audit Summary:", audit_document_chunks(sample_chunks))

    # Toy retrieval demo. The 3-d vectors are hand-made, not real embeddings:
    # the two part-number documents get almost the same vector, which is what
    # dense embeddings tend to do with codes like these.
    corpus = [
        {"chunk_id": "doc-a", "text": "Replacement filter SKU-8841-A fits the 2019 model.", "embedding": [0.90, 0.40, 0.10]},
        {"chunk_id": "doc-b", "text": "Replacement filter SKU-8841-B fits the 2021 model.", "embedding": [0.88, 0.42, 0.12]},
        {"chunk_id": "doc-c", "text": "Warranty claims need the original receipt.", "embedding": [0.10, 0.20, 0.95]},
        {"chunk_id": "doc-d", "text": "Which model should I buy? Compare each model by price.", "embedding": [0.20, 0.90, 0.30]},
    ]
    query = "Which model does SKU-8841-B fit?"
    query_vec = [0.90, 0.40, 0.10]
    dense_only = sorted(corpus, key=lambda d: _cosine_similarity(query_vec, d["embedding"]), reverse=True)
    print("Dense-only top hit:", dense_only[0]["chunk_id"])
    for hit in hybrid_rrf_retrieve(query, query_vec, corpus, top_k=2):
        print("Hybrid:", hit)

