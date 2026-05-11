from html import escape
from pathlib import Path
from string.templatelib import Interpolation
from typing import Any, Literal

from hypetext import Interpreter
from ovld import ovld

from .bridge import Cell, CellContext
from .js import js


class BucheInterpreter(Interpreter):
    cell: Cell

    def _js_serialize(self, value):
        return js(self.cell.srx.serialize(type(value), value, CellContext(self.cell)))

    def gen(self, value: Path, fmt: str, tag: str, attr: object):
        yield ("lit", str(self.cell.bridge.url(value)))

    @ovld(priority=1)
    def gen(self, value: object, fmt: Literal["js"], tag: str, attr: str):
        yield ("lit", escape(self._js_serialize(value)))

    @ovld(priority=1)
    def gen(self, value: object, fmt: Literal["js"], tag: str, attr: None):
        yield ("lit", self._js_serialize(value))

    @ovld(priority=1)
    def gen(self, value: Interpolation, fmt: str, tag: Literal["script"], attr: Any):
        yield ("lit", self._js_serialize(value.value))
