import json
from dataclasses import dataclass
from string.templatelib import Template

from ovld import ovld, recurse


@dataclass
class SerializationState:
    indent: int = 0
    prefix: str = ""

    def deeper(self):
        ind = " " * self.indent
        return SerializationState(self.indent, self.prefix + ind)


@ovld
def js(x: object, *, indent: int = 0):
    return recurse(x, SerializationState(indent))


@ovld
def js(x: None, state: SerializationState):
    return "null"


@ovld
def js(x: bool, state: SerializationState):
    return "true" if x else "false"


@ovld
def js(x: int, state: SerializationState):
    return str(x)


@ovld
def js(x: float, state: SerializationState):
    return str(x)


@ovld
def js(x: str, state: SerializationState):
    return json.dumps(x)


@ovld
def js(x: list, state: SerializationState):
    if not state.indent:
        return "[" + ", ".join(recurse(item, state) for item in x) + "]"
    inner = state.deeper()
    items = (",\n" + inner.prefix).join(recurse(item, inner) for item in x)
    return f"[\n{inner.prefix}{items}\n{state.prefix}]"


@ovld
def js(x: dict, state: SerializationState):
    if not state.indent:
        return "{" + ", ".join(f"{json.dumps(k)}: {recurse(v, state)}" for k, v in x.items()) + "}"
    inner = state.deeper()
    items = (",\n" + inner.prefix).join(
        f"{json.dumps(k)}: {recurse(v, inner)}" for k, v in x.items()
    )
    return f"{{\n{inner.prefix}{items}\n{state.prefix}}}"


@ovld
def js(x: Template, state: SerializationState):
    parts = []
    for s, i in zip(x.strings, x.interpolations):
        parts.append(s)
        parts.append(recurse(i.value, state))
    parts.append(x.strings[-1])
    return "".join(parts)
