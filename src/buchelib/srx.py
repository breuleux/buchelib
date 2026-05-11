import inspect
from dataclasses import dataclass
from types import FunctionType

from ovld import Medley
from serieux import JSON

from .bridge import Cell, CellContext


@dataclass
class ResponseId:
    id: str
    cell: Cell

    def resolve(self, value):
        self.cell.command(type="resolve", value=value, response_id=self.id)

    def reject(self, error):
        self.cell.command(type="resolve", error=str(error), response_id=self.id)


@Cell.register_type_default
@dataclass
class Call:
    function: FunctionType
    args: list[JSON]
    response_id: ResponseId

    def __post_init__(self):
        self.cell = self.response_id.cell

    async def call(self):
        try:
            params = list(inspect.signature(self.function).parameters.values())
            for p in params:
                if p.annotation is inspect.Parameter.empty:
                    raise TypeError(
                        f"Parameter '{p.name}' of {self.function.__name__} has no type annotation"
                    )
            deserialized = [
                self.cell.srx.deserialize(p.annotation, arg) for p, arg in zip(params, self.args)
            ]
            result = await self.function(*deserialized)
            self.response_id.resolve(result)
            return result
        except Exception as exc:
            self.response_id.reject(exc)
            raise


class BucheSerieux(Medley):
    ######################
    # Custom serializers #
    ######################

    def serialize(self, t: type[FunctionType], obj: FunctionType, ctx: CellContext):
        return t"embed({ctx.cell.register_function(obj)})"

    ########################
    # Custom deserializers #
    ########################

    def deserialize(self, t: type[FunctionType], obj: str, ctx: CellContext):
        for fn, tag in ctx.cell.function_registry.items():
            if tag == obj:
                return fn
        else:
            raise Exception(f"No function with tag: {obj}")

    def deserialize(self, t: type[ResponseId], obj: str, ctx: CellContext):
        return ResponseId(obj, ctx.cell)
