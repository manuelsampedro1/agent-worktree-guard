# Agent Worktree Guard

Protect user changes before and after a coding-agent run.

`agent-worktree-guard` records a snapshot of the current Git working tree, then checks a later working tree for two common failure modes:

- pre-existing dirty files changed, disappeared, or drifted while the agent was supposed to avoid them,
- new dirty paths appeared outside the files or globs the task explicitly allowed.

The tool is dependency-free, local-first, and designed for Codex, Claude Code, review packets, and pre-commit handoffs where "do not touch unrelated user changes" must be enforceable instead of only stated in chat.

## Install

```sh
python3 -m pip install -e .
```

Or run without installing:

```sh
PYTHONPATH=src python3 -m agent_worktree_guard --help
```

## Quick Start

Take a snapshot before handing a dirty repo to an agent:

```sh
PYTHONPATH=src python3 -m agent_worktree_guard snapshot --output /tmp/worktree-snapshot.json
```

After the run, allow only the expected paths and check for drift:

```sh
PYTHONPATH=src python3 -m agent_worktree_guard check /tmp/worktree-snapshot.json \
  --allow "src/**" \
  --allow "tests/**"
```

If a pre-existing user change was edited or removed, or if a new dirty path appears outside the allowlist, the command exits non-zero.

## Example Output

```md
# Agent Worktree Guard

Verdict: `blocked`

## Issues

- Protected file drifted: `notes/user-draft.md`
- Unexpected dirty path outside allowlist: `scripts/deploy.sh`
```

## Commands

### `snapshot`

Creates a JSON snapshot:

```sh
agent-worktree-guard snapshot --output /tmp/worktree-snapshot.json
```

Snapshot fields include Git root, branch, HEAD, dirty paths, Git status code, file existence, and SHA-256 hashes for files that exist on disk.

### `check`

Compares the current working tree to a snapshot:

```sh
agent-worktree-guard check /tmp/worktree-snapshot.json --allow README.md --allow "src/**"
```

Useful options:

- `--allow`: file or glob the current task is allowed to change. Repeatable.
- `--format json`: machine-readable verdict.
- `--allow-head-change`: do not warn if HEAD changed after the snapshot.
- `--base-dir`: repo directory to inspect.

## Development

```sh
make test
make lint
make build
make smoke
```

## Fit With The Agent Workflow Stack

- `agent-task-contract`: define what the task is allowed to touch.
- `agent-scope-guard`: check a diff against expected paths.
- `agent-worktree-guard`: protect pre-existing dirty files and unplanned working-tree drift.
- `agent-proof-packet`: include the guard result as review evidence.
