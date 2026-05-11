import asyncio
import json
import os
from dataclasses import dataclass, field
from glob import glob
from itertools import count
from pathlib import Path
from types import FunctionType
from typing import Any, Iterable
from uuid import uuid4

from ovld import ovld, recurse
from serieux import Context, Serieux, serieux
from serieux.features.tagset import TagDict

_current_id = count()


@ovld
def _expand_paths(p: str):
    if "*" in p:
        for path in glob(p):
            yield from recurse(Path(path))
    else:
        yield from recurse(Path(p))


@ovld
def _expand_paths(p: Path):
    if p.is_dir():
        raise Exception("Availing a directory is not allowed. Avail individual files.")
    yield p


@ovld
def _expand_paths(p: Iterable):
    for x in p:
        yield from recurse(x)


class Bridge:
    def __init__(self, fd=None):
        if fd is None:
            fd = int(os.environ.get("BUCHE_CONTROL_FD", 5))
        self.ctlin = os.fdopen(fd, "r", buffering=1)
        self.ctlout = os.fdopen(os.dup(fd), "w", buffering=1)
        self.catalogue = {}

    def send(self, payload):
        self.ctlout.write(json.dumps(payload) + "\n")

    def _pack_file(self, nonce, rel, p):
        match p.suffix:
            case ".css":
                packed = {"mimetype": "text/css", "content": p.read_text()}
            case ".js":
                packed = {"mimetype": "text/javascript", "content": p.read_text()}
            case other:
                raise Exception(f"Unsupported format: {other}")
        self.catalogue[str(p)] = f"buche://nonce/{nonce}/{rel}"
        return packed

    def avail(self, *files):
        concrete = list(_expand_paths(files))
        paths = [Path(f).resolve() for f in concrete]
        base = os.path.commonpath([str(p.parent) for p in paths])
        nonce = str(uuid4())
        self.send(
            {
                "type": "library",
                "nonce": nonce,
                "files": {
                    str(rel := p.relative_to(base)): self._pack_file(nonce, rel, p) for p in paths
                },
            }
        )

    def url(self, p):
        sp = str(Path(p).resolve())
        if sp not in self.catalogue:
            self.avail(p)
        return self.catalogue[sp]


_tagdict_defaults = {}


@dataclass(kw_only=True)
class Cell:
    bridge: Bridge
    id: str = "main"
    interpreter_class: type
    tagset: TagDict = field(default_factory=lambda: TagDict(_tagdict_defaults))
    srx: Serieux = field(default_factory=lambda: serieux)
    function_registry: dict = field(default_factory=dict)

    def __post_init__(self):
        self.interpreter = self.interpreter_class(self)

    @classmethod
    def register_type_default(cls, fn):
        _tagdict_defaults[f"{fn.__module__}:{fn.__qualname__}"] = fn

    def register_type(self, *args, **kwargs):
        self.tagset.register(*args, **kwargs)

    async def inputs(self):
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, self.bridge.ctlin)
        async for line in reader:
            data = json.loads(line)
            data.pop("to", None)
            yield self.deserialize(data)

    def avail(self, *files):
        return self.bridge.avail(*files)

    def command(self, **args):
        return self.bridge.send(
            {
                "type": "cell_send",
                "message": args,
                "to": {"target": "terminal", "cell": self.id},
            }
        )

    @ovld
    def serialize(self, obj: FunctionType):
        if obj not in self.function_registry:
            self.function_registry[obj] = f"F{next(_current_id)}"
        return t"document.embed({self.function_registry[obj]})"

    @ovld
    def serialize(self, obj: object):
        return self.srx.serialize(Any @ self.tagset, obj, CellContext(self))

    def deserialize(self, data):
        return self.srx.deserialize(Any @ self.tagset, data, CellContext(self))

    def body(self):
        from .selection import Selection

        return Selection(cell=self)


class CellContext(Context):
    cell: Cell
