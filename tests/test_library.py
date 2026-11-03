import hashlib
import hmac

import pytest

from buchelib.library import library_declaration

SALT = "s" * 64


def test_declaration(tmp_path):
    (tmp_path / "app.js").write_text("import './util.js';")
    (tmp_path / "util.js").write_text("export {};")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG")

    lib, message = library_declaration(
        {"js/app.js": tmp_path / "app.js", "/js/util.js": tmp_path / "util.js"}, salt=SALT
    )
    assert message["type"] == "library"
    assert message["id"] == lib.id
    assert len(lib.id) == 32
    entry = message["files"]["js/app.js"]
    assert entry["file"] == str((tmp_path / "app.js").resolve())
    assert entry["mimetype"] == "text/javascript"
    assert (
        entry["proof"]
        == hmac.new(SALT.encode(), b"import './util.js';", hashlib.sha256).hexdigest()
    )
    assert set(message["files"]) == {"js/app.js", "js/util.js"}
    assert lib.url("js/app.js") == f"lib://{lib.id}/js/app.js"
    assert lib / "/js/util.js" == f"lib://{lib.id}/js/util.js"

    # A list of files: each at its own name.
    _, message2 = library_declaration([tmp_path / "logo.png"], salt=SALT)
    assert message2["files"]["logo.png"]["mimetype"] == "image/png"


def test_id(tmp_path):
    (tmp_path / "a.js").write_text("a")
    first, _ = library_declaration([tmp_path / "a.js"], salt=SALT)
    again, _ = library_declaration([tmp_path / "a.js"], salt=SALT)
    other_salt, _ = library_declaration([tmp_path / "a.js"], salt="t" * 64)
    (tmp_path / "a.js").write_text("b")
    edited, _ = library_declaration([tmp_path / "a.js"], salt=SALT)
    assert first.id == again.id
    assert len({first.id, other_salt.id, edited.id}) == 3


def test_errors(tmp_path, monkeypatch):
    monkeypatch.delenv("BUCHE_LIB_SALT", raising=False)
    (tmp_path / "a.js").write_text("a")
    with pytest.raises(RuntimeError):
        library_declaration([tmp_path / "a.js"])
    with pytest.raises(FileNotFoundError):
        library_declaration([tmp_path / "missing.js"], salt=SALT)
    with pytest.raises(ValueError):
        library_declaration([tmp_path / "a.js", tmp_path / "a.js"], salt=SALT)


def test_inline(tmp_path, monkeypatch):
    monkeypatch.delenv("BUCHE_LIB_SALT", raising=False)
    # Inline content only: no salt needed.
    lib, message = library_declaration({"data.json": b'{"a": 1}', "x.bin": b"\xff\x00"})
    assert message["files"]["data.json"] == {
        "mimetype": "application/json",
        "content": '{"a": 1}',
        "encoding": "utf-8",
    }
    assert message["files"]["x.bin"]["encoding"] == "base64"
    assert message["files"]["x.bin"]["content"] == "/wA="
    again, _ = library_declaration({"data.json": b'{"a": 1}', "x.bin": b"\xff\x00"})
    assert again.id == lib.id

    # Mixed with files: the salt is needed for those.
    (tmp_path / "a.js").write_text("a")
    with pytest.raises(RuntimeError):
        library_declaration({"a.js": tmp_path / "a.js", "d.json": b"{}"})
    _, mixed = library_declaration({"a.js": tmp_path / "a.js", "d.json": b"{}"}, salt=SALT)
    assert "proof" in mixed["files"]["a.js"]
    assert "content" in mixed["files"]["d.json"]
