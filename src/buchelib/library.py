"""Libraries: files served to GUIs at ``lib://<id>/<path>``.

A library is declared once, with a proof for each file that this process can
read it; the shell (cq) checks the proofs and supplies the files to buche when
they are needed, so the content is never sent from here, and buche keeps it in
a store shared by every session. Files in a library can refer to each other by
relative URLs (``import "./util.js"``).

    lib = cell.library({"app.js": here / "app.js", "app.css": here / "app.css"})
    body.print(t'<link rel="stylesheet" href={lib.url("app.css")}>')
    # In inline scripts, go through buche.lib() (needed in the browser view):
    body.exec(t"import(buche.lib({lib.url('app.js')}))")

A file can also be given as ``bytes``: its content is then sent along with the
declaration (no file, no proof — and no shell needed if all files are given
that way):

    lib = cell.library({"data.json": json.dumps(data).encode()})

The id is derived from the proofs, which only someone able to read the files
(with this process's salt) can compute: unguessable, and the same for the same
files. Changing a file changes the id, so declare the library again after
editing its files. (For inline content, the id derives from the content.)
"""

import base64
import hashlib
import hmac
import mimetypes
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

#: The environment variable the shell puts this process's salt in.
SALT_ENV = "BUCHE_LIB_SALT"

# mimetypes.guess_type varies across platforms; these matter for browsers
# (module scripts need a JavaScript MIME type).
_MIMETYPES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".html": "text/html",
    ".svg": "image/svg+xml",
    ".wasm": "application/wasm",
    ".map": "application/json",
}


def mimetype_for(path: Path) -> str:
    return (
        _MIMETYPES.get(path.suffix.lower())
        or mimetypes.guess_type(path.name)[0]
        or "application/octet-stream"
    )


@dataclass(frozen=True)
class Library:
    """A declared library."""

    id: str
    #: The files, by path in the library (bytes: inline content).
    files: Mapping[str, Path | bytes]

    @property
    def base(self) -> str:
        return f"lib://{self.id}/"

    def url(self, path: str = "") -> str:
        """The URL of `path` in the library (its root, by default)."""
        return self.base + path.lstrip("/")

    def __truediv__(self, path: str) -> str:
        return self.url(path)


def _normalize(files) -> dict[str, Path | bytes]:
    if isinstance(files, Mapping):
        pairs = [
            (str(k).lstrip("/"), v if isinstance(v, (bytes, bytearray)) else Path(v))
            for k, v in files.items()
        ]
    elif isinstance(files, (str, os.PathLike)):
        pairs = [(Path(files).name, Path(files))]
    elif isinstance(files, Iterable):
        pairs = [(Path(f).name, Path(f)) for f in files]
    else:
        raise TypeError(f"library files: expected a mapping or paths, got {files!r}")
    result = {}
    for key, path in pairs:
        if key in result:
            raise ValueError(f"library: two files for {key!r}")
        result[key] = bytes(path) if isinstance(path, (bytes, bytearray)) else path.resolve()
    return result


def library_declaration(files, salt: str | None = None) -> tuple[Library, dict]:
    """The library for `files` and the message declaring it.

    `files` maps paths in the library to files, or to their content (bytes);
    or is a list of files, each at its own name. The salt defaults to the one
    the shell gave us (only needed for files).
    """
    salt = salt if salt is not None else os.environ.get(SALT_ENV)
    files = _normalize(files)
    if not salt and any(isinstance(f, Path) for f in files.values()):
        raise RuntimeError(
            f"lib:// libraries of files need a shell that serves them (cq): ${SALT_ENV}"
            " is not set (give the content as bytes instead)"
        )
    key = (salt or "").encode()
    entries = {}
    seal = {}
    for libpath, file in sorted(files.items()):
        if isinstance(file, bytes):
            try:
                content, encoding = file.decode("utf-8"), "utf-8"
            except UnicodeDecodeError:
                content, encoding = base64.b64encode(file).decode(), "base64"
            entries[libpath] = {
                "mimetype": mimetype_for(Path(libpath)),
                "content": content,
                "encoding": encoding,
            }
            seal[libpath] = hashlib.sha256(file).hexdigest()
            continue
        if not file.is_file():
            raise FileNotFoundError(f"library: {file} is not a file")
        entries[libpath] = {
            "file": str(file),
            "mimetype": mimetype_for(file),
            "proof": hmac.new(key, file.read_bytes(), hashlib.sha256).hexdigest(),
        }
        seal[libpath] = entries[libpath]["proof"]
    digest = hashlib.sha256()
    for libpath, entry in entries.items():
        digest.update(f"{libpath}\0{entry['mimetype']}\0{seal[libpath]}\n".encode())
    lib = Library(id=digest.hexdigest()[:32], files=files)
    return lib, {"type": "library", "id": lib.id, "files": entries}
