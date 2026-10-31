import asyncio
import hashlib
import json
import os
import re
import select
from dataclasses import dataclass, field, replace
from functools import cached_property
from itertools import count
from pathlib import Path
from types import FunctionType
from typing import Any
from uuid import uuid4

from ovld import ovld
from serieux import JSON, Context, Serieux, serialize, serieux
from serieux.features.tagset import TagDict

from .files import expand_paths, export_file

here = Path(__file__).parent

_current_id = count()
type_ = type

# Messages are addressed by arrays. The terminal is ["$term"]; a process speaks
# from ["$proc", ...rest], a *relative* address: the parent coquille rewrites
# it into its own subtree (["$proc", "cq", <pid>, ...rest]) on the way out, and
# strips `to` addresses back to this form on the way in.
TERM = ["$term"]
PROC = "$proc"
MAIN = "$main"


def _plain_text(html):
    # The new protocol echoes plain styled text, not HTML markup.
    return re.sub(r"<[^>]+>", "", html or "")


@dataclass(kw_only=True)
class ResolveRequest:
    method: str
    path: str
    params: dict[str, str] = field(default_factory=dict)
    request_id: str
    cell: "Cell" = None

    def resolve_to(self, p: Path, mimetype: str = None):
        payload = {
            "type": "resolve",
            "path": self.path,
            "request_id": self.request_id,
            "status": 200,
            **export_file(p.suffix, p),
        }
        if mimetype is not None:
            payload["mimetype"] = mimetype
        self.cell.command(**payload)


@dataclass
class Resize:
    width: float = None
    height: float = None
    cell: "Cell" = None


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
        if self.prompt is None or self.prompt.handler is None:
            return None
        return await self.prompt.handler(self.prompt, self.message)


def _write(payload, fd):
    data = (json.dumps(payload) + "\n").encode()
    written = 0
    while written < len(data):
        select.select([], [fd], [])
        try:
            written += os.write(fd, data[written:])
        except BlockingIOError:
            pass


class Bridge:
    def __init__(self, fd=None):
        if fd is None:
            fd = int(os.environ.get("BUCHE_CONTROL_FD", 5))
        self.ctlin = os.fdopen(fd, "r", buffering=1)
        self._outfd = os.dup(fd)
        # Availed files: local path -> served URL, and back (for answering
        # resource requests from cells that missed the cache push).
        self.catalogue = {}
        self.served = {}
        self.cells = {}
        self.cells_by_address = {}
        self.prompts = {}
        self.prompts_by_address = {}
        self.schemas = {}

    def send(self, payload):
        _write(payload, self._outfd)

    # ── structured data ──────────────────────────────────────────────────────

    def data(self, payload, type=None):
        type = type or type_(payload)
        if type not in self.schemas:
            self.schemas[type] = type.__name__
        payload = serialize(type, payload)
        payload["$schema"] = self.schemas[type]
        # Data is per-cell now: deliver it to every cell that registered a
        # handler for this schema (the old data channel was global). With no
        # registered handler anywhere, send it to the main cell.
        targets = [c for c in self.cells.values() if self.schemas[type] in c.data_schemas]
        if not targets:
            targets = [self.main_cell]
        for cell in targets:
            cell.command(type="data", data=payload)

    # ── files ────────────────────────────────────────────────────────────────

    def _serve_url(self, p):
        digest = hashlib.sha1(str(p).encode()).hexdigest()[:10]
        return f"/_buchelib/{digest}/{p.name}"

    def avail(self, *files):
        concrete = [Path(p).resolve() for p in expand_paths(list(files))]
        for p in concrete:
            packed = export_file(p.suffix, p)
            if packed["mimetype"] is None:
                raise Exception(f"Unsupported format: {p.suffix}")
            url = self.catalogue.get(str(p)) or self._serve_url(p)
            self.catalogue[str(p)] = url
            self.served[url] = p
            # Push into every live GUI; a cell created later is answered on
            # demand (see _resolve_from_catalogue).
            for cell in self.cells.values():
                cell.command(type="resolve", path=url, status=200, **packed)

    def url(self, p):
        sp = str(Path(p).resolve())
        if sp not in self.catalogue:
            self.avail(Path(sp))
        return self.catalogue[sp]

    def _resolve_from_catalogue(self, cell, payload):
        """Answer a GUI resource request from an availed file, if we have it.
        (The old terminal served availed files itself; now the library does.)
        Returns whether the request was answered."""
        path = payload.get("path")
        p = self.served.get(path)
        if p is None:
            return False
        cell.command(
            type="resolve",
            request_id=payload.get("request_id"),
            path=path,
            status=200,
            **export_file(p.suffix, p),
        )
        return True

    # ── cells & prompts ──────────────────────────────────────────────────────

    @cached_property
    def srx(self):
        from .srx import BucheSerieux

        return (Serieux + BucheSerieux)()

    def _setup_cell(self, cell, config=None):
        self.cells[cell.id] = cell
        self.cells_by_address[tuple(cell.address)] = cell
        # The terminal only routes commands to cells that exist; bring the
        # cell into existence first (under coquille it takes the process's
        # placeholder over, and its look). Its ✕ ends the process once the
        # process has nothing else on screen.
        cell.configure(**(config or {}))
        cell.body().exec(here / "lib.js")
        return cell

    @cached_property
    def main_cell(self):
        from .htmlgen import BucheInterpreter

        return self._setup_cell(
            Cell(bridge=self, interpreter_class=BucheInterpreter, srx=self.srx, id="main")
        )

    def cell(self, echo=None, behavior="background", id=None, under=None, name=None, ranges=None):
        from .htmlgen import BucheInterpreter

        name = name or uuid4().hex

        cell = Cell(
            bridge=self,
            interpreter_class=BucheInterpreter,
            srx=self.srx,
            id=name,
        )
        if under is not None:
            # Nest the cell under another entry (e.g. the prompt that produced
            # it): the cell's address extends the parent's (prompt "claude" +
            # name "1" → ["$proc", "claude", "1"], shown as `claude.1`), so the
            # terminal associates the cell with the prompt — its echo and
            # status hang below the prompt, and closing it sweeps the cell.
            parent = under.address if isinstance(under, Prompt) else list(under)
            cell.address = [*parent, name]
        config = {
            "background": behavior == "background",
            "sticky": behavior == "sticky",
        }
        if echo is not None:
            config["submission"] = {
                "content": {"text": _plain_text(echo), "ranges": ranges or []}
            }
        if id is not None:
            # Repeating the command's id lets the terminal focus the cell.
            config["id"] = id
        return self._setup_cell(cell, config)

    def prompt(self, label, handler=None, language=None, prompt_html=None, hue=200, chroma=0.5):
        # `language` is unused: highlighting now comes from parse answers the
        # process itself sends back (a prompt configure with a request_id).
        prompt = Prompt(bridge=self, label=label, handler=handler, address=[PROC, label])
        self.send(
            {
                "type": "configure",
                "kind": "prompt",
                "from": prompt.address,
                "to": TERM,
                "label": label,
                "color": f"oklch(0.65 {chroma} {hue})",
                # StyledText requires both `text` and `ranges`.
                "input": {"context": {"text": _plain_text(prompt_html) or "}}", "ranges": []}},
            }
        )
        self.prompts[label] = prompt
        self.prompts_by_address[tuple(prompt.address)] = prompt
        return prompt

    # ── incoming messages ────────────────────────────────────────────────────

    def _cell_for(self, to):
        return self.cells_by_address.get(tuple(to or []), None) or self.main_cell

    async def _lines(self):
        """The messages the terminal sends: one JSON object per line of the
        control channel."""
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, self.ctlin)
        async for line in reader:
            yield json.loads(line)

    def _served(self, cell, payload):
        """Whether `payload` (a GUI message) is a resource request the
        catalogue answered for `cell`."""
        return (
            isinstance(payload, dict)
            and payload.get("type") == "resolve"
            and self._resolve_from_catalogue(cell, payload)
        )

    async def __aiter__(self):
        async for data in self._lines():
            typ = data.get("type")
            if typ == "data":
                # A GUI message relayed by the terminal.
                payload = data.get("data")
                cell = self._cell_for(data.get("to"))
                if not self._served(cell, payload):
                    yield CellMessage(message=payload, cell=cell)
            elif typ in ("command", "parse", "signal"):
                prompt = self.prompts_by_address.get(tuple(data.get("to") or []), None)
                yield PromptMessage(message=data, prompt=prompt)
            else:
                yield CellMessage(message=data, cell=self._cell_for(data.get("to")))


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
        self.address = [PROC, MAIN] if self.id == "main" else [PROC, self.id]
        self.data_schemas = set()
        self.interpreter = self.interpreter_class(self)

    @classmethod
    def register_type_default(cls, fn):
        _tagdict_defaults[f"{fn.__module__}:{fn.__qualname__}"] = fn
        return fn

    def register_type(self, *args, **kwargs):
        self.tagset.register(*args, **kwargs)

    def register_function(self, fn):
        if fn not in self.function_registry:
            self.function_registry[fn] = f"F{next(_current_id)}"
        return self.function_registry[fn]

    def parse_message(self, msg):
        msg = dict(msg)
        msg.pop("to", None)
        msg.pop("from", None)
        typ = msg.pop("type", None)
        if typ == "message":
            data = msg.pop("data")
            if "response_id" in msg:
                data["response_id"] = msg["response_id"]
            return self.deserialize(data)
        if typ == "resolve":
            return replace(self.srx.deserialize(ResolveRequest, msg), cell=self)
        elif typ == "resize":
            pixel = msg.get("pixel") or {}
            return Resize(width=pixel.get("width"), height=pixel.get("height"), cell=self)
        else:
            return RawMessage(msg)

    def map_files(self, mapping):
        for pth, file in mapping.items():
            file = Path(file)
            self.bridge.served[str(pth)] = file
            # No request_id: this pre-pushes the resource into the GUI's
            # cache (a later request for the path is then instant).
            self.command(
                type="resolve", path=str(pth), status=200, **export_file(file.suffix, file)
            )

    async def inputs(self):
        async for msg in self.bridge._lines():
            typ = msg.get("type")
            if typ == "data":
                payload = msg.get("data")
                if not self.bridge._served(self, payload):
                    yield self.parse_message(payload)
            elif typ == "resize":
                yield self.parse_message(msg)
            else:
                yield RawMessage(msg)

    def avail(self, *files):
        return self.bridge.avail(*files)

    def command(self, **args):
        # The protocol schemas are strict: optional fields must be absent,
        # not null.
        args = {k: v for k, v in args.items() if v is not None}
        return self.bridge.send(
            {"type": "send", "from": self.address, "to": TERM, "message": args}
        )

    def configure(self, **options):
        options = {k: v for k, v in options.items() if v is not None}
        # buchelib cells are GUIs (they render HTML).
        self.bridge.send(
            {"type": "configure", "kind": "frame", "from": self.address, "to": TERM, **options}
        )

    def close(self, return_code=0):
        self.bridge.send(
            {
                "type": "close",
                "from": self.address,
                "to": TERM,
                "outcome": {
                    "type": "success" if return_code == 0 else "error",
                    "code": return_code,
                },
            }
        )

    def register_data_handlers(self, handlers):
        schemas = {t.__name__: code for t, code in handlers.items()}
        self.data_schemas.update(schemas)
        self.command(type="register_schemas", schemas=schemas)

    def data(self, payload, type=None):
        self.bridge.data(payload, type=type)

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
    address: list = None
