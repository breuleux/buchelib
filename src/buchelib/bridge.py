import asyncio
import json
import os
import select
from dataclasses import dataclass, field
from functools import cached_property
from itertools import count
from pathlib import Path
from types import FunctionType
from typing import Any
from uuid import uuid4

from ovld import ovld
from serieux import JSON, Context, Serieux, serieux
from serieux.features.tagset import TagDict

from .files import expand_paths, export_file

here = Path(__file__).parent

_current_id = count()


@dataclass
class ResolveRequest:
    method: str
    path: str
    request_id: str

    async def respond(self, p: Path):
        pass


@dataclass
class Resize:
    width: float = None
    height: float = None


@dataclass
class RawMessage:
    message: JSON


@dataclass
class CellMessage:
    message: JSON
    cell: Cell

    def parse(self):
        return self.cell.parse_message(self.message)

    async def dispatch(self):
        await self.parse().call()


@dataclass
class PromptMessage:
    message: JSON
    prompt: Prompt

    async def dispatch(self):
        return await self.prompt.handler(self.prompt, self.message)


class Bridge:
    def __init__(self, fd=None):
        if fd is None:
            fd = int(os.environ.get("BUCHE_CONTROL_FD", 5))
        self.ctlin = os.fdopen(fd, "r", buffering=1)
        self._outfd = os.dup(fd)
        self.catalogue = {}
        self.cells = {}
        self.prompts = {}

    def send(self, payload):
        data = (json.dumps(payload) + "\n").encode()
        written = 0
        while written < len(data):
            select.select([], [self._outfd], [])
            try:
                written += os.write(self._outfd, data[written:])
            except BlockingIOError:
                pass

    def _pack_file(self, nonce, rel, p):
        packed = export_file(p.suffix, p)
        if packed["mimetype"] is None:
            raise Exception(f"Unsupported format: {p.suffix}")
        self.catalogue[str(p)] = f"buche://nonce/{nonce}/{rel}"
        return packed

    def map_files(self, mapping):
        for pth, file in mapping.items():
            self.send(
                {
                    "type": "resolve",
                    "path": pth,
                    "method": "GET",
                    **export_file(file.suffix, file),
                    "to": {"target": "terminal", "cell": "main"},
                }
            )

    def avail(self, *files):
        concrete = list(expand_paths(files))
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

    @cached_property
    def srx(self):
        from .srx import BucheSerieux

        return (Serieux + BucheSerieux)()

    def __setup_cell(self, cell):
        self.cells[cell.id] = cell
        cell.body().exec(here / "lib.js")
        return cell

    @cached_property
    def main_cell(self):
        from .htmlgen import BucheInterpreter

        cell = Cell(
            bridge=self,
            interpreter_class=BucheInterpreter,
            srx=self.srx,
            id="main",
        )
        self.__setup_cell(cell)
        return cell

    def cell(self, echo=None):
        from .htmlgen import BucheInterpreter

        _id = uuid4().hex

        cell = Cell(
            bridge=self,
            interpreter_class=BucheInterpreter,
            srx=self.srx,
            id=_id,
        )
        self.send(
            {
                "type": "cell_create",
                "address": {"cell_id": _id},
                "to": {"target": "terminal", "cell": _id},
                "mode": "data",
                "echo_html": echo,
            }
        )
        self.__setup_cell(cell)
        return cell

    def prompt(self, label, handler=None, language=None, prompt_html=None):
        prompt = Prompt(bridge=self, label=label, handler=handler)
        self.send(
            {
                "type": "prompt_create",
                "to": {"target": "terminal", "prompt": "python"},
                "address": {"prompt_id": label},
                "prompt": prompt_html or "<span style='color:#4ec9b0;'>}</span>",
                "tab_html": label,
                "name": label,
                "tag": "python",
                "language": language,
            }
        )
        self.prompts[label] = prompt
        return prompt

    async def __aiter__(self):
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, self.ctlin)
        async for line in reader:
            data = json.loads(line)
            to = data.pop("to", {})
            if prid := to.get("prompt_id", None):
                yield PromptMessage(message=data, prompt=self.prompts.get(prid, None))
            else:
                cell_id = to.get("cell_id", "main")
                yield CellMessage(message=data, cell=self.cells.get(cell_id, None))


_tagdict_defaults = {}


@dataclass(kw_only=True)
class Cell:
    bridge: Bridge
    id: str = "main"
    interpreter_class: type
    tagset: TagDict = field(default_factory=lambda: TagDict(_tagdict_defaults))
    srx: Serieux = field(default_factory=lambda: serieux)
    function_registry: dict = field(default_factory=dict)
    handler: Any = None

    def __post_init__(self):
        self.address = {"cell_id": self.id} if self.id != "main" else {}
        self.interpreter = self.interpreter_class(self)

    @classmethod
    def register_type_default(cls, fn):
        _tagdict_defaults[f"{fn.__module__}:{fn.__qualname__}"] = fn

    def register_type(self, *args, **kwargs):
        self.tagset.register(*args, **kwargs)

    def register_function(self, fn):
        if fn not in self.function_registry:
            self.function_registry[fn] = f"F{next(_current_id)}"
        return self.function_registry[fn]

    def parse_message(self, msg):
        msg.pop("to", None)
        typ = msg.pop("type")
        if typ == "message":
            return self.deserialize(msg.pop("data"))
        elif typ == "resolve":
            return self.srx.deserialize(ResolveRequest, msg)
        elif typ == "resize":
            return self.srx.deserialize(Resize, msg)
        else:
            return RawMessage(msg)

    async def inputs(self):
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, self.bridge.ctlin)
        async for line in reader:
            msg = json.loads(line)
            yield self.parse_message(msg)

    def avail(self, *files):
        return self.bridge.avail(*files)

    def command(self, **args):
        return self.bridge.send(
            {
                "type": "cell_send",
                "message": args,
                "address": self.address,
                "to": {"target": "terminal", "cell": self.id},
            }
        )

    def configure(self, **options):
        self.bridge.send(
            {
                "type": "cell_configure",
                "address": self.address,
                "to": {"target": "terminal", "cell": self.id},
                **options,
            }
        )

    def close(self, return_code=0):
        self.bridge.send(
            {
                "type": "cell_close",
                "address": self.address,
                "to": {"target": "terminal", "cell": self.id},
                "return_code": return_code,
            }
        )

    @ovld
    def serialize(self, obj: FunctionType):
        return t"embed({self.register_function(obj)})"

    @ovld
    def serialize(self, obj: object):
        return self.srx.serialize(Any @ self.tagset, obj, CellContext(self))

    def deserialize(self, data):
        if "$class" not in data:
            return data
        return self.srx.deserialize(Any @ self.tagset, data, CellContext(self))

    def body(self):
        from .selection import Selection

        return Selection(cell=self)


class CellContext(Context):
    cell: Cell


@dataclass(kw_only=True)
class Prompt:
    bridge: Bridge
    label: str
    handler: Any
