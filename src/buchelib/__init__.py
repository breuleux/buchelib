from pathlib import Path

from serieux import Serieux

from .bridge import Bridge, Cell
from .htmlgen import BucheInterpreter
from .srx import BucheSerieux

here = Path(__file__).parent

__bridge = None
__main_cell = None


def bridge():
    global __bridge
    if not __bridge:
        __bridge = Bridge()
    return __bridge


def main_cell():
    global __main_cell
    if not __main_cell:
        __main_cell = Cell(
            bridge=bridge(),
            interpreter_class=BucheInterpreter,
            srx=(Serieux + BucheSerieux)(),
            id="main",
        )
        __main_cell.body().exec(here / "lib.js")
    return __main_cell
