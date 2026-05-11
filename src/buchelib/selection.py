from dataclasses import dataclass
from string.templatelib import Template

from hypetext import html

from .bridge import Cell


@dataclass(kw_only=True)
class Selection:
    cell: Cell
    selector: str = None

    def __getitem__(self, selector):
        sel = f"{self.selector} {selector}" if self.selector else selector
        return type(self)(cell=self.cell, selector=sel)

    def exec(self, code):
        if isinstance(code, Template):
            code = "".join(self.cell.interpreter.string_parts(code, "", "script"))

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
