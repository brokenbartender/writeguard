import os
from writeguard import (
    snapshot, verify, detect_unexpected_changes, catch_phantom_write,
    Status, Op, Claim, FileSnapshot,
)


def test_create_verified(tmp_path):
    f = tmp_path / "new.py"
    before = snapshot([f])                    # file doesn't exist yet
    f.write_text("print('hi')")               # agent creates it
    r = verify([{"path": str(f), "op": "create"}], before)
    assert r.ok
    assert r.checks[0].status is Status.VERIFIED


def test_create_failed_when_not_created(tmp_path):
    f = tmp_path / "missing.py"
    before = snapshot([f])
    r = verify([{"path": str(f), "op": "create"}], before)   # agent lied — never created
    assert not r.ok
    assert r.checks[0].status is Status.FAILED
    assert "did NOT verify" in r.correction_prompt


def test_modify_verified(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("old")
    before = snapshot([f])
    f.write_text("new content")               # real modification
    r = verify([{"path": str(f), "op": "modify"}], before)
    assert r.ok


def test_modify_drift_when_unchanged(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("same")
    before = snapshot([f])
    # agent claims modify but leaves it byte-identical
    r = verify([{"path": str(f), "op": "modify"}], before)
    assert not r.ok
    assert r.checks[0].status is Status.DRIFT


def test_delete_verified_and_failed(tmp_path):
    f = tmp_path / "gone.py"
    f.write_text("bye")
    before = snapshot([f])
    f.unlink()
    assert verify([{"path": str(f), "op": "delete"}], before).ok
    # now claim delete on a file that still exists
    g = tmp_path / "stays.py"; g.write_text("x")
    b2 = snapshot([g])
    r = verify([{"path": str(g), "op": "delete"}], b2)
    assert r.checks[0].status is Status.FAILED


def test_content_hash_assertion(tmp_path):
    import hashlib
    f = tmp_path / "h.py"
    before = snapshot([f])
    f.write_text("exact")
    good = hashlib.sha256(b"exact").hexdigest()
    assert verify([Claim(str(f), Op.CREATE, content_hash=good)], before).ok
    bad = verify([Claim(str(f), Op.CREATE, content_hash="deadbeef")], before)
    assert bad.checks[0].status is Status.DRIFT


def test_detect_unexpected_changes(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_text("1"); b.write_text("2")
    before = snapshot([a, b])
    b.write_text("changed")                   # b changed but only a was claimed
    unexpected = detect_unexpected_changes(before, [a])
    assert str(b.resolve()) in unexpected
    assert str(a.resolve()) not in unexpected


def test_path_containment(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret")
    snap = FileSnapshot.capture(outside, root=tmp_path)   # root restricts to tmp_path
    assert snap.exists is False                           # blocked — outside root


def test_catch_phantom_write():
    # claims a write in prose, no tool called
    assert catch_phantom_write("Sure! I have updated config.py for you.", tool_called=None)
    # a real write tool ran → no warning
    assert catch_phantom_write("I have updated config.py", tool_called="Edit") is None
    # no claim → no warning
    assert catch_phantom_write("Here is how the config works.", tool_called=None) is None


def test_no_claims_is_ok():
    assert verify([], {}).ok
