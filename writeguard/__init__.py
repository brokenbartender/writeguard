"""
writeguard — verify your AI coding agent actually did what it claims to the filesystem.

LLM coding agents hallucinate. They say "I've updated config.py" when no write happened,
or claim a MODIFY that left the file byte-identical. writeguard catches that: snapshot the
files before the agent runs, then verify each claimed operation against real disk state
(SHA-256), and generate a correction prompt for the ones that lied. Framework-agnostic —
works with any agent (OpenAI, Claude, LangChain, custom) because it checks the *disk*, not
the agent's words.

    from writeguard import snapshot, verify, catch_phantom_write

    before = snapshot(["config.py", "main.py"])          # before the agent edits
    # ... agent claims it created config.py and modified main.py ...
    result = verify(
        [{"path": "config.py", "op": "create"},
         {"path": "main.py",   "op": "modify"}],
        before,
    )
    if not result.ok:
        print(result.correction_prompt)                   # feed back to the agent

    # Fast heuristic before you even run verify():
    warning = catch_phantom_write(agent_message, tool_called=None)
    if warning:
        print(warning)  # agent *said* it wrote a file but called no write tool
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional

__version__ = "0.1.0"
__all__ = [
    "Op", "Status", "FileSnapshot", "Claim", "CheckResult", "GuardResult",
    "snapshot", "verify", "detect_unexpected_changes", "catch_phantom_write",
    "PHANTOM_PHRASES", "WRITE_TOOL_NAMES",
]


class Op(str, Enum):
    CREATE = "create"
    MODIFY = "modify"
    DELETE = "delete"
    READ = "read"


class Status(str, Enum):
    VERIFIED = "verified"   # claim matches disk
    DRIFT = "drift"         # file exists but not as claimed (e.g. MODIFY left it unchanged)
    FAILED = "failed"       # claim did not happen at all


@dataclass(frozen=True)
class FileSnapshot:
    """A content + metadata snapshot of one path. `sha256` is '' when the file is absent."""
    path: str
    exists: bool
    size: int
    sha256: str

    @staticmethod
    def capture(path: str | Path, root: Optional[Path] = None) -> "FileSnapshot":
        p = Path(path).resolve()
        # Optional containment: never snapshot outside `root` (defends against path traversal
        # when paths come from untrusted model output).
        if root is not None:
            try:
                p.relative_to(Path(root).resolve())
            except ValueError:
                return FileSnapshot(str(p), False, 0, "")
        try:
            if not p.exists() or not p.is_file():
                return FileSnapshot(str(p), False, 0, "")
            data = p.read_bytes()
            return FileSnapshot(str(p), True, len(data), hashlib.sha256(data).hexdigest())
        except OSError:
            return FileSnapshot(str(p), False, 0, "")


@dataclass(frozen=True)
class Claim:
    """A claimed filesystem operation. `content_hash` optionally asserts the resulting bytes."""
    path: str
    op: Op
    content_hash: Optional[str] = None

    @staticmethod
    def coerce(obj) -> "Claim":
        if isinstance(obj, Claim):
            return obj
        return Claim(
            path=obj["path"],
            op=Op(str(obj["op"]).lower()),
            content_hash=obj.get("content_hash"),
        )


@dataclass
class CheckResult:
    claim: Claim
    status: Status
    detail: str

    @property
    def ok(self) -> bool:
        return self.status is Status.VERIFIED


@dataclass
class GuardResult:
    ok: bool
    checks: list[CheckResult] = field(default_factory=list)
    correction_prompt: Optional[str] = None

    @property
    def failures(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.ok]


def snapshot(paths: Iterable[str | Path], root: Optional[str | Path] = None) -> dict[str, FileSnapshot]:
    """Capture snapshots for `paths` (deduped), keyed by resolved path string."""
    r = Path(root) if root is not None else None
    out: dict[str, FileSnapshot] = {}
    for p in paths:
        key = str(Path(p).resolve())
        if key not in out:
            out[key] = FileSnapshot.capture(p, r)
    return out


def _check(claim: Claim, before: FileSnapshot, after: FileSnapshot) -> CheckResult:
    op = claim.op
    if op is Op.CREATE:
        if not after.exists:
            return CheckResult(claim, Status.FAILED, f"not created: {claim.path}")
        if before.exists:
            return CheckResult(claim, Status.DRIFT, f"already existed before create: {claim.path}")
        if claim.content_hash and after.sha256 != claim.content_hash:
            return CheckResult(claim, Status.DRIFT, "content hash mismatch after create")
        return CheckResult(claim, Status.VERIFIED, f"created ({after.size} bytes)")
    if op is Op.MODIFY:
        if not after.exists:
            return CheckResult(claim, Status.FAILED, f"missing after modify: {claim.path}")
        if after.sha256 == before.sha256:
            return CheckResult(claim, Status.DRIFT, f"unchanged after claimed modify: {claim.path}")
        if claim.content_hash and after.sha256 != claim.content_hash:
            return CheckResult(claim, Status.DRIFT, "content hash mismatch after modify")
        return CheckResult(claim, Status.VERIFIED, f"modified ({before.size} → {after.size} bytes)")
    if op is Op.DELETE:
        if after.exists:
            return CheckResult(claim, Status.FAILED, f"still exists after claimed delete: {claim.path}")
        if not before.exists:
            return CheckResult(claim, Status.DRIFT, f"did not exist before delete: {claim.path}")
        return CheckResult(claim, Status.VERIFIED, "deleted")
    if op is Op.READ:
        if not after.exists:
            return CheckResult(claim, Status.FAILED, f"missing for read: {claim.path}")
        return CheckResult(claim, Status.VERIFIED, f"read ({after.size} bytes)")
    return CheckResult(claim, Status.DRIFT, f"unknown op: {op}")


def verify(claims, before: dict[str, FileSnapshot], root: Optional[str | Path] = None) -> GuardResult:
    """
    Verify claimed operations against real disk state, using `before` snapshots.
    `claims` is an iterable of Claim or dicts like {"path": ..., "op": "modify"}.
    """
    parsed = [Claim.coerce(c) for c in claims]
    if not parsed:
        return GuardResult(ok=True)
    r = Path(root) if root is not None else None
    checks: list[CheckResult] = []
    for claim in parsed:
        key = str(Path(claim.path).resolve())
        b = before.get(key) or FileSnapshot.capture(claim.path, r)
        a = FileSnapshot.capture(claim.path, r)
        checks.append(_check(claim, b, a))
    ok = all(c.ok for c in checks)
    prompt = None
    if not ok:
        lines = "\n".join(f"  - [{c.status.value.upper()}] {c.claim.op.value} {c.claim.path}: {c.detail}"
                          for c in checks if not c.ok)
        prompt = (
            "Some file operations you claimed did NOT verify against the actual filesystem:\n"
            f"{lines}\n\n"
            "Do not claim a change without actually performing the write. "
            "Re-apply the failed operations using your file-write tool, then continue."
        )
    return GuardResult(ok=ok, checks=checks, correction_prompt=prompt)


def detect_unexpected_changes(before: dict[str, FileSnapshot], claimed_paths: Iterable[str | Path]) -> list[str]:
    """Files that changed on disk but were NOT among the claimed paths (silent drift)."""
    claimed = {str(Path(p).resolve()) for p in claimed_paths}
    changed = []
    for key, b in before.items():
        if key in claimed:
            continue
        a = FileSnapshot.capture(key)
        if a.sha256 != b.sha256 or a.exists != b.exists:
            changed.append(key)
    return changed


# Phrases that signal a model *claiming* a write in prose.
PHANTOM_PHRASES = (
    "i have updated", "i have modified", "i changed the file", "i've updated",
    "i added the code to", "the file has been updated", "i wrote the changes",
    "i saved the file", "the code has been added", "i have created", "i've created",
)

# Common write-tool names — if one of these ran, the claim is backed by an action.
WRITE_TOOL_NAMES = {
    "write_to_file", "replace_file_content", "multi_replace_file_content",
    "write_file", "str_replace", "str_replace_editor", "edit", "edit_file",
    "create_file", "apply_patch", "Write", "Edit", "MultiEdit",
}


def catch_phantom_write(text: str, tool_called: Optional[str]) -> Optional[str]:
    """
    Cheap pre-check: did the model *say* it edited a file while calling no write tool?
    Returns a correction string, or None if fine. Use before the full `verify()` pass.
    """
    if tool_called and tool_called in WRITE_TOOL_NAMES:
        return None
    low = (text or "").lower()
    for phrase in PHANTOM_PHRASES:
        if phrase in low:
            return (
                f'You claimed to change a file ("{phrase}"), but no write tool was executed. '
                "Actually call your file-write tool now — do not report a change you did not make."
            )
    return None
