# TruthGuard

**Adversarial Verification for Multi-Agent Document Q&A** — Virtusa Jatayu Season 6, Team NeuralNinjas.

See [AGENTS.md](AGENTS.md) for the full specification and working rules.

## Quick start (after cloning)

```bash
cp .env.example .env          # fill in LLM_API_KEY if you want real LLM answers
make setup                    # installs Python dependencies
make ingest                   # indexes the seed corpus in data/raw/acme/
make ask Q="What is a manager's expense approval limit?" USER=employee
make test
make eval
```

The baselines run without an LLM API key and without downloading any ML model.

## Structure

```
truthguard/   Python package — five pipeline phases + shared code
data/         documents, index, benchmark
eval/         benchmark runner and hand-written cases
tests/        smoke tests per phase + end-to-end
web/          Next.js frontend (Phase 5, not built in the skeleton)
```
