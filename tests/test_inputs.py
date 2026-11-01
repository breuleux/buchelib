import asyncio

from buchelib.bridge import Cell, RawMessage, Resize, ResolveRequest


def _cell():
    # These message types are parsed without touching the bridge.
    return Cell(bridge=None, interpreter_class=lambda cell: None)


def test_resize_message_parses():
    obj = _cell().parse_message({"type": "resize", "pixel": {"width": 900, "height": 500}})
    assert isinstance(obj, Resize)
    assert (obj.width, obj.height) == (900, 500)


def test_unknown_message_parses_as_raw():
    assert isinstance(_cell().parse_message({"type": "close"}), RawMessage)


def test_resize_call_is_a_noop():
    # A loop that only drives callbacks must survive a resize.
    assert asyncio.run(Resize(width=900, height=500).call()) is None


def test_raw_message_call_is_a_noop():
    assert asyncio.run(RawMessage({"type": "close"}).call()) is None


def test_resolve_request_has_no_call():
    # An unanswered resource request is a bug in the interface: say so.
    assert not hasattr(ResolveRequest, "call")
