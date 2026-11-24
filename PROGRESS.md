\# Project Progress \& Collaboration State



\## 1. Ground Rules (The Karpathy CLAD.md Principles)

We strictly adhere to the four principles:

1\. \*\*Think Before Coding:\*\* Surface assumptions, ask questions, present tradeoffs before generating code.

2\. \*\*Simplicity First:\*\* Minimum code to solve the problem. No premature abstractions. No features not explicitly requested.

3\. \*\*Surgical Changes:\*\* Touch only what is necessary. Do not refactor adjacent code unless it breaks our immediate goal.

4\. \*\*Goal-Driven Execution:\*\* Every step has a verifiable success criterion (usually a passing test).



\## 2. Core Constraints

\- \*\*Zero-Cost:\*\* No paid API keys. All providers must have free tiers or run locally.

\- \*\*Providers:\*\* Groq, Gemini, Ollama (local). (Z.ai held in reserve).

\- \*\*Architecture Target:\*\* The Anirban Chakraborty LLM Gateway diagram (Routing, Caching, Guardrails, Cost Tracking).



\## 3. Documented Decisions (See DECISIONS.md for full ADRs)

\- \*\*Cache:\*\* v0.1 uses In-Memory Dict (exact match only). Redis/Semantic cache deferred to v0.2.

\- \*\*Guardrails:\*\* Presidio with `en\_core\_web\_sm` (12MB) for input PII masking.

\- \*\*Cost Tracking:\*\* "Shadow costs" (equivalent USD) tracked per virtual key. In-memory ledger for v0.1.

\- \*\*Routing:\*\* Primary = Groq, Fallback 1 = Gemini, Fallback 2 = Ollama.

\- \*\*Testing:\*\* Split into `functional/` and `red\_team/`. All pytest tests use `unittest.mock` to intercept upstream HTTP calls. A separate `smoke\_test.py` exists for live testing.



\## 4. Version Roadmap

\- \*\*v0.1 (Current Goal):\*\* 

&#x20; - Repo setup + Documentation.

&#x20; - FastAPI gateway with `/v1/chat/completions`, `/health`, `/usage`, `/admin/keys`.

&#x20; - Multi-provider routing (Groq -> Gemini -> Ollama).

&#x20; - Input PII masking (Presidio).

&#x20; - In-memory exact cache and key store.

&#x20; - Functional \& Red-Team test suites (mocked).

&#x20; - Manual smoke test script.

\- \*\*v0.2 (Future):\*\* 

&#x20; - Docker Compose (Redis + Postgres).

&#x20; - Semantic Cache using Ollama embeddings (`nomic-embed-text`).

&#x20; - Persistent key store and usage ledger.

\- \*\*v0.3 (Future):\*\*

&#x20; - Output Guardrails (Llama Guard or similar local model).

&#x20; - Advanced routing (cost/latency based).



\## 5. Current Status

\- \[x] Architecture and principles agreed upon.

\- \[x] v0.1 scope and provider matrix finalized.

\- \[x] Initial documentation drafted (README, DECISIONS, PROGRESS).

\- \[x] \*\*v0.1 COMPLETE:\*\* FastAPI proxy, exact in-memory cache, Presidio PII guardrail, shadow cost ledger, and multi-provider routing (Groq/Gemini/Ollama) implemented.

\- \[x] \*\*Tests:\*\* 8/8 passing (4 functional, 4 red-team). `pytest.ini` added.

\- \[x] \*\*Live Smoke Test:\*\* Groq and Ollama verified live. Gemini verified as reachable but currently returning 503 (documented in ADR-010).

\- \[ ] \*\*NEXT UP (v0.2.1):\*\* Expose `cost\_usd` in `/usage` endpoint (ADR-011).

\- \[ ] \*\*DECISION REQUIRED:\*\* Docker for Redis (v0.2.2) - Yes or No?



\## 6. Instruction for the AI (When the User Says "Read PROGRESS.md")



If the user starts a new conversation and asks you to "Read PROGRESS.md", you MUST:

1\. Read this entire file, plus `DECISIONS.md` and `README.md`.

2\. Acknowledge the four Karpathy principles in Section 1 and state that you will follow them.

3\. Confirm the Core Constraints in Section 2, specifically the zero-cost constraint.

4\. Check the "Current Status" in Section 5. Do NOT write code for completed items.

5\. Look at the "NEXT UP" item in Section 5 and ask the user if they want to proceed with it, OR if they want to change the plan.

6\. Do NOT write any code until the user explicitly says "Go ahead" or confirms the next step.



\## ADR-010: Free-Tier Providers Are Unreliable Under Load

\*\*Decision:\*\* Accept 503/502 failures from Gemini free tier as expected behavior.

\*\*Why:\*\* Google's free-tier Gemini API is known to return 503 under load.

Confirmed via uvicorn logs during v0.1 smoke test: 

`Server error '503 Service Unavailable' for url 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions'`.

The gateway's fallback chain (Gemini -> Ollama) handles this correctly.

\*\*Tradeoff:\*\* Forced-Gemini smoke tests will occasionally fail with 502

(gateway's generic "all providers failed" response). This is not a bug.

\*\*Mitigation:\*\* Retry after 5–10 minutes, or switch to a less-loaded model.



\## ADR-011: Cost Observability Deferred to v0.2

\*\*Decision:\*\* The `cost\_usd` calculation exists in `main.py` but is not yet exposed via `/usage`.

\*\*Why:\*\* We focused on verifying the logic of token counting (via red-team tests) first.

\*\*Tradeoff:\*\* The "Shadow Cost" mechanism cannot be visually verified by the user yet.

\*\*Upgrade path:\*\* v0.2.1 will add `cost\_usd` to the in-memory ledger and return it in `/usage`, along with a functional test proving the dollar math.



