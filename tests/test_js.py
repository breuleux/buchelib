from buchelib.js import js


def test_primitives():
    assert js(None) == "null"
    assert js(True) == "true"
    assert js(False) == "false"
    assert js(42) == "42"
    assert js(3.14) == "3.14"
    assert js("hello") == '"hello"'
    assert js('say "hi"') == '"say \\"hi\\""'


def test_list():
    assert js([1, 2, 3]) == "[1, 2, 3]"
    assert js([]) == "[]"
    assert js([[1, 2], [3, 4]]) == "[[1, 2], [3, 4]]"


def test_dict():
    assert js({"a": 1}) == '{"a": 1}'
    assert js({}) == "{}"
    assert js({"x": [1, 2]}) == '{"x": [1, 2]}'


def test_indent_list():
    assert js([1, 2, 3], indent=2) == "[\n  1,\n  2,\n  3\n]"


def test_indent_dict():
    assert js({"a": 1, "b": 2}, indent=2) == '{\n  "a": 1,\n  "b": 2\n}'


def test_indent_nested():
    result = js({"a": [1, 2]}, indent=2)
    assert result == '{\n  "a": [\n    1,\n    2\n  ]\n}'


def test_indent_zero_is_compact():
    assert js([1, 2, 3], indent=0) == "[1, 2, 3]"


def test_template():
    name = "world"
    result = js(t"hello {name}")
    assert result == 'hello "world"'


def test_template_with_number():
    x = 42
    result = js(t"value is {x}")
    assert result == "value is 42"


def test_template_with_nested_structure():
    data = [1, 2]
    result = js(t"data = {data}")
    assert result == "data = [1, 2]"


def test_template_with_indent():
    data = [1, 2]
    result = js(t"data = {data}", indent=2)
    assert result == "data = [\n  1,\n  2\n]"
