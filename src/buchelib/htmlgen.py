from html import escape
from pathlib import Path
from typing import Literal

from hypetext import Interpreter
from ovld import ovld

from .bridge import Cell
from .js import js


class BucheInterpreter(Interpreter):
    cell: Cell

    def gen(self, value: Path, fmt: str, attr: object):
        yield ("lit", str(self.cell.bridge.url(value)))

    @ovld(priority=1)
    def gen(self, value: object, fmt: Literal["embed"], attr: str):
        yield ("lit", escape(js(self.cell.serialize(value))))

    @ovld(priority=1)
    def gen(self, value: object, fmt: Literal["embed"], attr: None):
        yield ("lit", js(self.cell.serialize(value)))
