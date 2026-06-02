# AGENTS.md

## Goal

Build a small, dependency-free CLI that protects user working-tree changes around coding-agent runs.

## Constraints

- Python standard library only.
- Keep commands local-first and Git-based.
- Do not store secrets, tokens, absolute private paths, or terminal transcripts in examples.
- Prefer explicit non-zero exits over vague warnings when protected files drift.

## Verification

Run before closing a change:

```sh
make test
make lint
make build
make smoke
```

If behavior changes, update `README.md`, tests, and examples together.
