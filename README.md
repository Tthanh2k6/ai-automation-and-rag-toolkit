# AI Automation, Hybrid RAG & Workflow Engineering Toolkit

<div align="center">
  <p align="center">
    <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.11+" />
    <img src="https://img.shields.io/badge/FastAPI-Async_Microservices-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
    <img src="https://img.shields.io/badge/OpenAI-Structured_Outputs_(JSON_Schema)-412991?style=flat-square&logo=openai&logoColor=white" alt="OpenAI Structured Outputs" />
    <img src="https://img.shields.io/badge/RAG-Hybrid_BM25_%2B_Vector_RRF-FF6B00?style=flat-square" alt="Hybrid RAG" />
    <img src="https://img.shields.io/badge/PostgreSQL-Supabase_RLS_%2B_pgTAP-336791?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL RLS" />
  </p>
</div>

---

Production-ready reference implementations for **Hybrid RAG Pipeline Diagnostics**, **FastAPI + OpenAI Structured Outputs (`json_schema`)**, **High-Throughput Stream Backpressure & Micro-Batching**, **Google Sheets / Apps Script Route Optimization**, and **PostgreSQL Row-Level Security (`pgTAP`) / ERP BI Connectors**.

## 🚀 Included Engineering Modules

| Module | File | What It Solves |
| :--- | :--- | :--- |
| **1. Hybrid RAG Pipeline Auditor (`BM25 + Dense RRF`)** | [`src/rag_hybrid_rerank_auditor.py`](./src/rag_hybrid_rerank_auditor.py) | Diagnoses chunk-boundary fragmentation and benchmarks pure dense cosine search against **Hybrid BM25 + Vector Reciprocal Rank Fusion (`RRF, k=60`)** with similarity cutoff guards to eliminate hallucinations. |
| **2. FastAPI + OpenAI Structured Outputs Service** | [`src/fastapi_openai_structured_rag_service.py`](./src/fastapi_openai_structured_rag_service.py) | Enforces 100% deterministic JSON schema responses (`strict: true`), handles token truncation (`finish_reason == "length"`), and implements idempotent webhook routing. |
| **3. Live Stream Backpressure & Micro-Batching Engine** | [`src/stream_backpressure_and_microbatch_engine.py`](./src/stream_backpressure_and_microbatch_engine.py) | Prevents queue memory exhaustion on live video/telemetry feeds using bounded ring buffers (`deque(maxlen=2)`), micro-batch inference grouping, and zero-downtime atomic model hot-swapping. |
| **4. Supabase / PostgreSQL RLS & `aal2` MFA `pgTAP` Suite** | [`sql_and_apps_script/supabase_rls_aal2_pgtap_audit_suite.sql`](./sql_and_apps_script/supabase_rls_aal2_pgtap_audit_suite.sql) | Verifies tenant isolation, `SECURITY INVOKER` views, `WITH CHECK` write guards, and `auth.jwt()->>'aal' = 'aal2'` enforcement across `anon` and `authenticated` roles. |
| **5. Google Sheets & Maps Smart Route Planner** | [`sql_and_apps_script/google_sheets_haversine_route_planner.js`](./sql_and_apps_script/google_sheets_haversine_route_planner.js) | Google Apps Script that geocodes property addresses, runs Nearest-Neighbor Haversine route optimization within a configurable time window, and outputs 1-click multi-stop Google Maps navigation URLs. |
| **6. Odoo ERP to Power BI Inventory Connector** | [`sql_and_apps_script/odoo_erp_to_powerbi_connector.py`](./sql_and_apps_script/odoo_erp_to_powerbi_connector.py) | Maps Odoo's core inventory models (`stock.quant`, `stock.move`, `product.product`, `stock.location`, `stock.warehouse`) to Power BI via PostgreSQL Views and `Web.Contents` (`RelativePath`) Power Query M scripts for cloud Scheduled Refresh. |

---

## ⚡ Quick Verification

```bash
# 1. Run the Hybrid RAG Diagnostic Benchmark (Dense vs. BM25 + Vector RRF)
python src/rag_hybrid_rerank_auditor.py

# 2. Run the Bounded Stream Backpressure & Atomic Model Hot-Swap Demo
python src/stream_backpressure_and_microbatch_engine.py

# 3. Run the FastAPI + OpenAI Structured RAG Pipeline Self-Test
python src/fastapi_openai_structured_rag_service.py
```

---

## 👤 Author

**Trung Thanh Tran** — Python, Playwright & AI Automation Developer  
- GitHub: [@Tthanh2k6](https://github.com/Tthanh2k6)
- Portfolio: [portfolio-red-theta-65.vercel.app](https://portfolio-red-theta-65.vercel.app/)
