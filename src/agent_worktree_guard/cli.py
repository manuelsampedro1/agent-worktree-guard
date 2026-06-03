from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


VALID_FORMATS = {"markdown", "json"}
HEX_DIGITS = set("0123456789abcdefABCDEF")


class GuardError(RuntimeError):
    pass


def run_git(args: Sequence[str], cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        raise GuardError(detail or f"git {' '.join(args)} failed")
    return proc.stdout


def git_root(base_dir: Path) -> Path:
    return Path(run_git(["rev-parse", "--show-toplevel"], base_dir).strip())


def git_head(root: Path) -> str:
    try:
        return run_git(["rev-parse", "HEAD"], root).strip()
    except GuardError:
        return ""


def git_branch(root: Path) -> str:
    try:
        return run_git(["branch", "--show-current"], root).strip()
    except GuardError:
        return ""


def sha256_file(path: Path) -> Optional[str]:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_existing_file(path: Path) -> str:
    if not path.exists():
        raise GuardError(f"Snapshot file not found: {path}")
    if not path.is_file():
        raise GuardError(f"Snapshot path is not a file: {path}")
    digest = sha256_file(path)
    if digest is None:
        raise GuardError(f"Could not hash snapshot file: {path}")
    return digest


def normalize_expected_sha256(value: str) -> str:
    expected = value.strip()
    if len(expected) != 64 or any(char not in HEX_DIGITS for char in expected):
        raise GuardError("--expect-snapshot-sha256 must be a 64-character hex SHA-256 digest")
    return expected.lower()


def normalize_path(path: str) -> str:
    return path.replace(os.sep, "/").strip("/")


def parse_status_line(line: str) -> Optional[Tuple[str, str]]:
    if not line:
        return None
    status = line[:2]
    path = line[3:]
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    return status, normalize_path(path)


def status_entries(root: Path) -> List[Dict[str, Any]]:
    output = run_git(["status", "--porcelain=v1", "--untracked-files=all"], root)
    entries: List[Dict[str, Any]] = []
    for raw in output.splitlines():
        parsed = parse_status_line(raw)
        if not parsed:
            continue
        status, rel_path = parsed
        abs_path = root / rel_path
        entries.append(
            {
                "path": rel_path,
                "status": status,
                "exists": abs_path.exists(),
                "sha256": sha256_file(abs_path),
            }
        )
    return sorted(entries, key=lambda item: item["path"])


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_snapshot(base_dir: Path) -> Dict[str, Any]:
    root = git_root(base_dir)
    return {
        "schema": "agent-worktree-guard/v1",
        "created_at": utc_now(),
        "git": {
            "root": str(root),
            "branch": git_branch(root),
            "head": git_head(root),
        },
        "dirty": status_entries(root),
    }


def write_json(data: Dict[str, Any], output: Optional[Path]) -> None:
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    if output:
        output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def load_snapshot(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise GuardError(f"Could not read snapshot JSON: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise GuardError(f"Invalid snapshot JSON: {exc}") from exc
    if data.get("schema") != "agent-worktree-guard/v1":
        raise GuardError("Unsupported snapshot schema")
    if not isinstance(data.get("dirty"), list):
        raise GuardError("Snapshot is missing dirty file entries")
    return data


def matches_any(path: str, patterns: Iterable[str]) -> bool:
    normalized = normalize_path(path)
    for pattern in patterns:
        normalized_pattern = normalize_path(pattern)
        if normalized == normalized_pattern or fnmatch.fnmatch(normalized, normalized_pattern):
            return True
    return False


def current_entry_map(root: Path) -> Dict[str, Dict[str, Any]]:
    return {entry["path"]: entry for entry in status_entries(root)}


def snapshot_entry_map(snapshot: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {entry["path"]: entry for entry in snapshot["dirty"]}


def compare_snapshot(
    snapshot: Dict[str, Any],
    base_dir: Path,
    allow: Sequence[str],
    allow_head_change: bool,
    snapshot_sha256: str,
) -> Dict[str, Any]:
    root = git_root(base_dir)
    current = current_entry_map(root)
    before = snapshot_entry_map(snapshot)
    issues: List[str] = []
    warnings: List[str] = []

    snapshot_head = snapshot.get("git", {}).get("head", "")
    current_head = git_head(root)
    if snapshot_head and current_head and snapshot_head != current_head and not allow_head_change:
        warnings.append(f"HEAD changed from `{snapshot_head[:12]}` to `{current_head[:12]}`")

    for path, entry in before.items():
        if matches_any(path, allow):
            continue
        current_entry = current.get(path)
        if current_entry is None:
            issues.append(f"Protected dirty path disappeared or became clean: `{path}`")
            continue
        if entry.get("exists") and not current_entry.get("exists"):
            issues.append(f"Protected file missing: `{path}`")
            continue
        if entry.get("sha256") != current_entry.get("sha256"):
            issues.append(f"Protected file drifted: `{path}`")

    for path in sorted(current):
        if path in before:
            continue
        if not matches_any(path, allow):
            issues.append(f"Unexpected dirty path outside allowlist: `{path}`")

    verdict = "blocked" if issues else "passed"
    return {
        "schema": "agent-worktree-guard/report/v1",
        "verdict": verdict,
        "base_dir": str(root),
        "snapshot_sha256": snapshot_sha256,
        "allowed": list(allow),
        "protected_paths": sorted(path for path in before if not matches_any(path, allow)),
        "current_dirty_paths": sorted(current),
        "issues": issues,
        "warnings": warnings,
    }


def render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Agent Worktree Guard",
        "",
        f"Verdict: `{report['verdict']}`",
        "",
        "## Issues",
        "",
    ]
    if report["issues"]:
        lines.extend(f"- {issue}" for issue in report["issues"])
    else:
        lines.append("- none")
    lines.extend(["", "## Warnings", ""])
    if report["warnings"]:
        lines.extend(f"- {warning}" for warning in report["warnings"])
    else:
        lines.append("- none")
    lines.extend(["", "## Snapshot Evidence", "", f"- SHA-256: `{report['snapshot_sha256']}`"])
    lines.extend(["", "## Allowed Paths", ""])
    if report["allowed"]:
        lines.extend(f"- `{pattern}`" for pattern in report["allowed"])
    else:
        lines.append("- none")
    lines.extend(["", "## Current Dirty Paths", ""])
    if report["current_dirty_paths"]:
        lines.extend(f"- `{path}`" for path in report["current_dirty_paths"])
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def emit_report(report: Dict[str, Any], output_format: str) -> None:
    if output_format == "json":
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(render_markdown(report))


def snapshot_command(args: argparse.Namespace) -> int:
    snapshot = make_snapshot(Path(args.base_dir))
    output_path = Path(args.output) if args.output else None
    write_json(snapshot, output_path)
    if args.output:
        snapshot_sha256 = sha256_existing_file(output_path)
        print(f"Wrote snapshot with {len(snapshot['dirty'])} dirty path(s): {args.output}")
        print(f"Snapshot SHA-256: {snapshot_sha256}")
    return 0


def check_command(args: argparse.Namespace) -> int:
    snapshot_path = Path(args.snapshot)
    snapshot_sha256 = sha256_existing_file(snapshot_path)
    if args.expect_snapshot_sha256:
        expected_sha256 = normalize_expected_sha256(args.expect_snapshot_sha256)
        if snapshot_sha256 != expected_sha256:
            raise GuardError(f"Snapshot hash mismatch: expected {expected_sha256}, got {snapshot_sha256}")
    snapshot = load_snapshot(snapshot_path)
    report = compare_snapshot(snapshot, Path(args.base_dir), args.allow, args.allow_head_change, snapshot_sha256)
    emit_report(report, args.format)
    return 1 if report["issues"] else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Protect user working-tree changes around coding-agent runs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot_parser = subparsers.add_parser("snapshot", help="Record current dirty working-tree paths.")
    snapshot_parser.add_argument("--base-dir", default=".", help="Git repository directory to inspect.")
    snapshot_parser.add_argument("--output", help="Path to write snapshot JSON. Defaults to stdout.")
    snapshot_parser.set_defaults(func=snapshot_command)

    check_parser = subparsers.add_parser("check", help="Check current working tree against a snapshot.")
    check_parser.add_argument("snapshot", help="Snapshot JSON created by the snapshot command.")
    check_parser.add_argument("--base-dir", default=".", help="Git repository directory to inspect.")
    check_parser.add_argument("--allow", action="append", default=[], help="Allowed file or glob. Repeatable.")
    check_parser.add_argument("--allow-head-change", action="store_true", help="Do not warn when HEAD changed.")
    check_parser.add_argument(
        "--expect-snapshot-sha256",
        help="Expected SHA-256 digest of the snapshot file. Blocks tampered or stale snapshots before comparison.",
    )
    check_parser.add_argument("--format", choices=sorted(VALID_FORMATS), default="markdown")
    check_parser.set_defaults(func=check_command)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except GuardError as exc:
        print(f"agent-worktree-guard: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
