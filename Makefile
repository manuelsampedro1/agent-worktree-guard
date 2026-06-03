.PHONY: test lint build smoke

test:
	PYTHONPATH=src python3 -m unittest discover -s tests

lint:
	python3 -m py_compile src/agent_worktree_guard/*.py tests/*.py

build:
	python3 -m compileall -q src tests

smoke:
	tmpdir="$$(mktemp -d)"; \
	snapshot="$${tmpdir}-snapshot.json"; \
	cd "$$tmpdir"; \
	git init -q; \
	git config user.name "Agent Worktree Guard"; \
	git config user.email "agent-worktree-guard@example.com"; \
	mkdir -p src notes; \
	printf 'stable\n' > README.md; \
	git add README.md; \
	git commit -qm initial; \
	printf 'user draft\n' > notes/user-draft.md; \
	PYTHONPATH="$(CURDIR)/src" python3 -m agent_worktree_guard snapshot --output "$$snapshot" >/tmp/agent-worktree-guard-snapshot.txt; \
	snapshot_hash="$$(python3 -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$$snapshot")"; \
	printf 'agent edit\n' > src/change.py; \
	PYTHONPATH="$(CURDIR)/src" python3 -m agent_worktree_guard check "$$snapshot" --expect-snapshot-sha256 "$$snapshot_hash" --allow "src/**" >/tmp/agent-worktree-guard-check.md; \
	printf 'changed by mistake\n' >> notes/user-draft.md; \
	if PYTHONPATH="$(CURDIR)/src" python3 -m agent_worktree_guard check "$$snapshot" --expect-snapshot-sha256 "$$snapshot_hash" --allow "src/**" >/tmp/agent-worktree-guard-blocked.md; then exit 1; else exit 0; fi
