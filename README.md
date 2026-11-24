\# RCGC LLM Gateway

\*\*Routing, Caching, Guardrails, and Cost tracking.\*\*



A hands-on, production-grade control plane for LLM applications. Built from scratch to demonstrate the core pillars of LLMOps without relying on heavy frameworks.



\## What this is (v0.1)

\- \*\*FastAPI\*\* proxy exposing `/v1/chat/completions`.

\- \*\*Exact-Match Cache\*\* (in-memory) to prevent duplicate upstream calls.

\- \*\*Input Guardrail\*\* using Microsoft Presidio (masks PII before it leaves your network).

\- \*\*Cost Tracking\*\* (shadow costs) per virtual key.

\- \*\*Multi-Provider Routing\*\* (Groq -> Gemini -> Ollama fallback).



\## What this is NOT (v0.1)

\- No Semantic Cache (requires vector DB, planned for v0.2).

\- No Persistence (in-memory cache and key store die on restart, planned for v0.2).

\- No Output Guardrails (planned for v0.3).

\- No Langfuse/OpenTelemetry integration (planned for v0.4).



\## Setup

1\. Install requirements: `pip install -r requirements.txt`

2\. Install spaCy model: `python -m spacy download en\_core\_web\_sm`

3\. Set env vars:

&#x20;  - `GROQ\_API\_KEY`

&#x20;  - `GEMINI\_API\_KEY`

4\. Run the server: `uvicorn main:app --reload`



\## Testing

\- Run fast automated tests: `pytest tests/`

\- Run live integration smoke test: `python smoke\_test.py` (requires valid API keys and local Ollama running).

