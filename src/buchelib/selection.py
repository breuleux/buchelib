from dataclasses import dataclass

from hypetext import html

from .bridge import Cell


@dataclass(kw_only=True)
class Selection:
    cell: Cell
    selector: str = None

    def __getitem__(self, selector):
        return type(self)(cell=self.cell, selector=f"{self.selector} {selector}")

    def exec(self, code):
        self.cell.command(type="exec", code=code)

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
