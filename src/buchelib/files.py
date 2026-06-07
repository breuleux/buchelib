import base64
from glob import glob
from pathlib import Path
from typing import Iterable, Literal

from ovld import ovld, recurse


@ovld
def expand_paths(p: str):
    if "*" in p:
        for path in glob(p):
            yield from recurse(Path(path))
    else:
        yield from recurse(Path(p))


@ovld
def expand_paths(p: Path):
    if p.is_dir():
        raise Exception("Availing a directory is not allowed. Avail individual files.")
    yield p


@ovld
def expand_paths(p: Iterable):
    for x in p:
        yield from recurse(x)


@ovld
def encode():
    pass


@ovld
def export_file(suffix: Literal[".css"], file: Path):
    return {
        "mimetype": "text/css",
        "content": file.read_text(),
        "encoding": "utf-8",
    }


@ovld
def export_file(suffix: Literal[".js"], file: Path):
    return {
        "mimetype": "text/javascript",
        "content": file.read_text(),
        "encoding": "utf-8",
    }


@ovld
def export_file(suffix: Literal[".png"] | Literal[".jpeg"], file: Path):
    content = open(file, "rb").read()
    return {
        "mimetype": "image/{suffix.lstrip('.')}",
        "content": base64.b64encode(content).decode(),
        "encoding": "base64",
    }


@ovld
def export_file(suffix: str, file: Path):
    content = open(file, "rb").read()
    return {
        "mimetype": None,
        "content": base64.b64encode(content).decode(),
        "encoding": "base64",
    }
