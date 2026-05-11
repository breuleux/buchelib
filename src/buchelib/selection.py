from dataclasses import dataclass
from pathlib import Path
from string.templatelib import Template

from hypetext import html
from ovld import ovld, recurse

from .bridge import Cell


@dataclass(kw_only=True)
class Selection:
    cell: Cell
    selector: str = None

    def __getitem__(self, selector):
        sel = f"{self.selector} {selector}" if self.selector else selector
        return type(self)(cell=self.cell, selector=sel)

    @ovld
    def exec(self, code: Path):
        recurse(code.read_text())

    @ovld
    def exec(self, code: Template):
        scode = "".join(self.cell.interpreter.string_parts(code, "", "script"))
        recurse(scode)

    @ovld
    def exec(self, code: str):
        self.cell.command(type="exec", code=code, selector=self.selector)

    def print(self, tpl):
        node = html(tpl)
        self.cell.command(
            type="html",
            mode="append",
            selector=self.selector,
            content="".join(self.cell.interpreter.string_parts(node)),
        )

    def set(self, tpl):
        node = html(tpl)
        self.cell.command(
            type="html",
            mode="set",
            selector=self.selector,
            content="".join(self.cell.interpreter.string_parts(node)),
        )
