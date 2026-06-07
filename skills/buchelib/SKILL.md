# buchelib — Guide to building HTML interfaces

buchelib is a Python library for producing HTML interfaces that run inside **buche** terminal iframes. A Python script drives the interface by sending HTML, CSS, and JavaScript to the cell; the browser can call back into Python via embedded async functions.

---

## Setup

### Script header

buchelib scripts should be self-contained. Use a `uv` shebang and embed all dependencies inline so the script runs without a pre-existing virtualenv:

```python
#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "buchelib",
#   "serieux",
# ]
# ///
```

Make the script executable (`chmod +x myscript.py`) and run it directly: `./myscript.py`.

### Checking availability

Before calling `main_cell()` or `bridge()`, you can check whether buche is actually running:

```python
from buchelib import is_available

if not is_available():
    print("Not running inside buche — falling back to plain output")
else:
    cell = main_cell()
    ...
```

`is_available()` returns `True` only when `BUCHE_CONTROL_FD` is set in the environment **and** the file descriptor it names is actually open. Use it to write scripts that degrade gracefully when run outside buche (e.g. in CI or a plain terminal).

### Boilerplate

```python
from buchelib import main_cell

cell = main_cell()
body = cell.body()
```

`body` is a `Selection` — a handle to the document body that lets you append HTML, run JavaScript, or narrow scope to a CSS selector.

---

## Injecting HTML

Use `body.print()` to append HTML. It accepts a **t-string** (Python template string). Interpolated values are automatically serialized to safe HTML.

**Self-closing tags** must be written with an explicit slash: `<input />`, `<br />`, `<img />`. Writing `<input>` without a closing slash causes hypetext to misparse the template, treating subsequent content as children of the tag.

```python
body.print(t'<h1>Hello, {username}!</h1>')
```

Use `body.set()` to replace the contents of the selection rather than append:

```python
body["#status"].set(t'<span>Done</span>')
```

To inject a Python string that is **already valid HTML** (e.g. output from a markdown renderer), use the `:raw` format spec to bypass escaping:

```python
html_string = markdown.markdown(text)
body["#output"].set(t"{html_string:raw}")
```

### Selecting sub-elements

Index a `Selection` with any CSS selector to scope subsequent operations:

```python
body["#hello"].exec(t"this.innerHTML = {message}")
```

Compound selectors accumulate (parent selector + child selector joined by a space).

---

## Serving static assets (CSS, JS files)

There are three ways to serve local files to the browser. Choose based on whether portability or simplicity matters more.

### 1. Embed in a template string (simplest)

Interpolate a `Path` directly into a t-string. buchelib rewrites it to a `buche://` URL and serves the file automatically:

```python
from pathlib import Path

body.print(t'<link rel="stylesheet" href={Path("styles.css")}>')
body.exec(Path("mylib.js"))
```

This is the easiest approach for scripts written specifically for buche. The downside is that the HTML/JS references `buche://` URLs, so it cannot be reused as-is in a regular web app.

### 2. Preload with `cell.map_files()` (process can exit early)

Send all assets upfront before the browser requests them. The browser uses normal `/`-prefixed paths, and buche serves them from its cache — even after the Python process has terminated:

```python
cell.map_files({
    "/styles.css": Path("styles.css"),
    "/app.js":     Path("app.js"),
})

body.print(t'<link rel="stylesheet" href="/styles.css">')
body.exec(Path("app.js"))
```

Use this when you want the script to exit (`cell.configure(sticky=True)`) but still have the interface remain fully functional. All assets must be known and sent upfront.

### 3. Serve on demand via `ResolveRequest` (process stays alive)

When the browser fetches a path the terminal doesn't have cached, it sends a `ResolveRequest` to Python. Handle it in the `cell.inputs()` loop and call `resolve_to()` to send the file back:

```python
from buchelib import ResolveRequest

body.print(t'<link rel="stylesheet" href="/styles.css">')

async for obj in cell.inputs():
    if isinstance(obj, ResolveRequest):
        if obj.path == "/styles.css":
            obj.resolve_to(Path("styles.css"))
    elif isinstance(obj, Callback):
        await obj.call()
```

This keeps normal web paths in the HTML/JS — the same markup works in a regular web server without modification. The tradeoff is that the Python process must stay alive to answer requests.

---

## Running JavaScript

`exec()` accepts a t-string, a plain string, or a `Path`.

**T-string** — use when you need to interpolate Python values (objects, functions) into JS. All `{expr}` interpolations are serialized to JS literals:

```python
body.exec(t'console.log({point})')
```

When `exec` is called on a sub-selection, `this` inside the script refers to the matched element:

```python
body["#hello"].exec(t"this.innerHTML = {label}")
```

**F-string or plain string** — use when your JS contains HTML-like tags (e.g. SVG, template literals with `<` or `>`). Hypetext parses the template for tags and can misinterpret angle brackets inside a script context. For those cases, build the code as a plain Python string and let `exec` take it directly:

```python
body.exec(f"""
    el.innerHTML = '<svg viewBox="0 0 300 44">...</svg>';
    const data = {json.dumps(values)};
""")
```

**Path** — loads and runs an entire JS file:

```python
body.exec(Path("mylib.js"))
```

### Variable scoping across `exec()` calls

Each `exec()` call runs in its own scope. Variables declared with `const` or `let` in one call are **not visible** in subsequent calls. To share a value across multiple `exec()` blocks, assign it to `window`:

```python
body.exec(t'window.myFn = {my_python_fn};')
body.exec(t'window.DATA = {data};')

body.exec(f"""
    // myFn and DATA are accessible here
    console.log(window.DATA);
    window.myFn();
""")
```

Plain `window.X` references also work as bare `X` in browser globals, so no special syntax is needed on the reading side.

---

## Calling Python from JavaScript — `embed`

buchelib automatically injects its client-side runtime, which provides the `embed` helper. `embed` wraps a Python async function so JavaScript can call it and `await` its result.

**Python side** — define an annotated async function (all parameters must be type-annotated so buchelib knows how to deserialize arguments):

```python
from serieux import JSON

async def square(x: JSON):
    await asyncio.sleep(0.5)   # non-blocking
    return x * x
```

**HTML side** — use `{square:js}` in an event handler attribute to embed the function:

```python
body.print(t'<button onclick="event.indicate({square:js}, 42)">Square 42</button>')
```

or call it directly in JS:

```python
body.exec(t'const result = await {square:js}(7)')
```

**Driving the event loop** — the script must process incoming messages. `cell.inputs()` is an async generator that yields one of four types:

| Type | When yielded | What to do |
|---|---|---|
| `Callback` | JS called an embedded Python function | `await obj.call()` — runs the function and resolves the JS promise |
| `ResolveRequest` | browser fetched a path not yet cached | `obj.resolve_to(Path(...))` — send the file back |
| `Resize` | the iframe was resized | read `obj.width` / `obj.height` |
| `RawMessage` | any other message type | read `obj.message` (a plain dict) |

Minimal loop (callbacks only):

```python
async for obj in cell.inputs():
    await obj.call()
```

Loop that also handles resource requests:

```python
from buchelib import Callback, ResolveRequest

async for obj in cell.inputs():
    if isinstance(obj, ResolveRequest):
        obj.resolve_to(Path(obj.path.lstrip("/")))
    elif isinstance(obj, Callback):
        await obj.call()
```

`Callback.call()` deserializes the arguments, calls the function, and sends the return value back to the browser as the resolved promise.

---

## Visual feedback — `event.indicate`

The runtime adds an `indicate` method directly to every `Event`. It automatically uses `event.currentTarget` (falling back to `event.target`) as the `eventTarget`, picking up the `indicator-selector` attribute from that element:

```html
<button onclick="event.indicate(myfn, 1, 2)" indicator-selector="#status">
  Run
</button>
```

This is the recommended pattern for button handlers — it keeps the HTML declarative and the indicator logic out of JavaScript.

Style the indicator class in your CSS:

```css
.buche-indicator {
    border: solid blue 3px;
    opacity: 0.6;
}
```

---

## Cell configuration

Use `cell.configure()` to send a `cell_configure` message to the terminal. Call it any time after the cell is created — typically right after initial rendering.

```python
cell.configure(sticky=True)   # keep focus on the cell when the process ends
cell.configure(background=True)  # defocus the cell and return focus to the prompt
```

**`sticky=True`** — useful for read-only output cells (weather forecasts, dashboards) where you want the result to remain visible and focused after the script exits.

**`background=True`** — useful for cells that run silently and should return control to the prompt immediately.

---

## Focus management

buche automatically focuses the element with **`id="prime-focus"`** when the cell is first added to the terminal. Always set this on whichever element should receive keyboard input first:

```python
body.print(t'<input id="prime-focus" type="text" placeholder="Search…">')
```

Only one element should carry `#prime-focus`.

For subsequent focus events (e.g. when the user clicks back into the cell after switching away), buche calls **`window.autofocus()`** if it is defined. Override it to control where focus lands on re-entry:

```javascript
window.autofocus = () => {
    document.getElementById('prime-focus').focus();
};
```

`#prime-focus` is still focused automatically on first insertion regardless of `window.autofocus`. Redefining `window.autofocus` only affects later focus events — use it when the right target changes over time (e.g. focus the currently selected row rather than a fixed element).

---

## Keyboard navigation

Because buche interfaces live inside iframes and are used from the keyboard, good keyboard support is essential. Prefer **arrow-key navigation** over Tab for structured content — it is more ergonomic and gives you full control over movement.

**Core pattern:** give the container `tabindex="0"` so it receives focus, give items `tabindex="-1"` so they can be focused programmatically but stay out of the Tab order, then handle `keydown` on the container.

**Lists** (Up/Down):

```html
<ul id="prime-focus" tabindex="0">
  <li tabindex="-1">Item A</li>
  <li tabindex="-1">Item B</li>
  <li tabindex="-1">Item C</li>
</ul>
```

```javascript
document.querySelector('ul').addEventListener('keydown', e => {
    const items = [...e.currentTarget.querySelectorAll('li')];
    const idx = items.indexOf(document.activeElement);
    if (e.key === 'ArrowDown') { e.preventDefault(); items[(idx + 1) % items.length].focus(); }
    if (e.key === 'ArrowUp')   { e.preventDefault(); items[(idx - 1 + items.length) % items.length].focus(); }
    if (e.key === 'Enter')     { items[idx]?.click(); }
});
```

**Tables / grids** (Up/Down/Left/Right):

```javascript
document.querySelector('table').addEventListener('keydown', e => {
    const table = e.currentTarget;
    const cells = [...table.querySelectorAll('td, th')];
    const cols = table.rows[0].cells.length;
    const idx = cells.indexOf(document.activeElement);
    const moves = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: cols, ArrowUp: -cols };
    if (e.key in moves) {
        e.preventDefault();
        cells[idx + moves[e.key]]?.focus();
    }
});
```

Make each cell focusable with `tabindex="-1"` and the table itself with `tabindex="0"`.

**Use `<button>` for actions** — buttons respond to Enter and Space without extra handling.

**Quit:** always bind `q` and/or `Escape` to terminate the interface. `window.close()` does not work — the Python process must be killed. Before killing the process, call `window.buche.blur()` to return focus to the terminal — without it, focus stays stuck in the cell because the blur call can't reach an already-terminated process. Define a Python callback that calls `os._exit(0)`, embed it, and call it (no need to await):

```python
async def quit():
    os._exit(0)
```

```javascript
const quitFn = {quit};  // in t-string exec
// ...
if (e.key === 'q' || e.key === 'Escape') { window.buche.blur(); quitFn(); }
```

If the exec block is an f-string (e.g. because it contains HTML tags), embed the function via `window` in a separate t-string exec first, so it is visible across blocks:

```python
body.exec(t'window.quitFn = {quit};')
body.exec(f"""
    // ... rest of JS ...
    if (e.key === 'q') {{ window.buche.blur(); quitFn(); }}
""")

**Help overlay:** keep the shortcut help hidden by default and toggle it with `?`. A simple approach:

```html
<div id="help" hidden>
  ↑↓ navigate · Enter select · q quit
</div>
```

```javascript
container.addEventListener('keydown', e => {
    if (e.key === '?') {
        document.getElementById('help').toggleAttribute('hidden');
        return;
    }
    // ... other keys
});
```

**Layout sizing:** the interface runs inside an iframe. Check `window.bucheInfo` for sizing hints:

- `bucheInfo.dynamicHeight` — if `false`, the iframe has a fixed height and you **may** use `height: 100%` / `height: 100vh` freely. If `true` or absent, the iframe grows to fit content and percentage heights collapse.
- `bucheInfo.maxHeight` — when `dynamicHeight` is not `false`, use this pixel value to size scrollable regions: subtract the heights of any fixed chrome (toolbars, footers) and apply the remainder as a fixed `height` on the scrollable container.

When neither condition applies, fall back to a sensible fixed height (e.g. `height: 400px`). Do **not** use `height: 100%` or `height: 100vh` in a dynamic-height iframe — they collapse to zero or overflow unexpectedly.

**Visual focus indicator:** never suppress the browser's focus outline. Customize it in CSS rather than removing it:

```css
:focus-visible {
    outline: 2px solid cornflowerblue;
    outline-offset: 2px;
}
```

---

## Building an interpreter

An **interpreter** integrates a REPL-style prompt into the buche terminal. The user types a command, presses Enter, and your Python code runs `eval` and writes output into a new cell.

### Setup

Use `bridge()` instead of `main_cell()`, then register a prompt with a handler:

```python
from buchelib import bridge as bridge_
from buchelib.interpreter import Interpreter

class MyInterpreter(Interpreter):
    async def eval(self, cell, command):
        cell.body().print(t"You typed: <b>{command}</b>")

async def main():
    bridge = bridge_()
    bridge.prompt("myprompt", handler=MyInterpreter(), language="text")

    async for obj in bridge:
        await obj.dispatch()

asyncio.run(main())
```

`bridge.prompt(label, handler, language)` sends a `prompt_create` message to buche, registering the prompt under `label`. `language` is passed to the editor for syntax highlighting (e.g. `"python"`, `"text"`).

The `async for obj in bridge` loop receives both cell messages and prompt messages and dispatches them to the right handler via `obj.dispatch()`.

### The `Interpreter` base class

Subclass `buchelib.interpreter.Interpreter` and override `eval`:

```python
class Interpreter:
    async def eval(self, cell, command):
        """Called for each submitted command. `cell` is a fresh output cell."""
        raise NotImplementedError()

    async def on_error(self, cell, error):
        """Called when eval raises. Default: re-raises."""
        raise error
```

The base class handles the full lifecycle automatically:
- `handle_prompt_submit` — creates a new output cell (with the echo HTML), calls `eval`, prints a non-`None` return value, then closes the cell.
- `handle_prompt_close` — raises `SystemExit(0)`.
- `handle_parse` — no-op; override for live-parse feedback.

### The `cell` object passed to `eval`

Each call to `eval` receives a freshly created `Cell`. Use it exactly like the cell from `main_cell()`:

```python
async def eval(self, cell, command):
    body = cell.body()
    body.print(t'<pre>{command}</pre>')
    # Do NOT call cell.close() — the base class does it automatically.
```

The base class calls `cell.close()` after `eval` returns (or `cell.close(1)` on error). Do not close the cell yourself unless you override `handle_prompt_submit`.

### Overriding `handle_prompt_submit`

If you need full control (e.g. streaming output, custom error display), override `handle_prompt_submit` directly:

```python
async def handle_prompt_submit(self, prompt, message):
    cell = prompt.bridge.cell(echo=message.get("echo_html"))
    try:
        await self.eval(cell, message["text"])
    except Exception as exc:
        cell.body().print(t'<pre style="color:red">{exc}</pre>')
        cell.close(1)
    else:
        cell.close()
```

### Quick reference

| Operation | How |
|---|---|
| Create bridge | `bridge = bridge_()` |
| Register prompt | `bridge.prompt(label, handler=MyInterpreter(), language="python")` |
| Dispatch all messages | `async for obj in bridge: await obj.dispatch()` |
| Write output in eval | `cell.body().print(t'...')` |
| Non-`None` return value | Printed automatically by base class |
| Error handling | Override `on_error(self, cell, error)` |

---

## Complete example

```python
import asyncio
from pathlib import Path
from serieux import JSON
from buchelib import main_cell

cell = main_cell()
body = cell.body()

async def square(x: JSON):
    await asyncio.sleep(0.5)
    return x * x

async def main():
    body.print(t'<link rel="stylesheet" href={Path("styles.css")}>')

    body.print(t"""
        <form onsubmit="return false">
            <input id="prime-focus" type="number" value="4" id="n">
            <button
                type="submit"
                indicator-selector="#result"
                onclick="event.indicate({square:js}, +this.form.querySelector('input').value)"
            >Square</button>
        </form>
        <div id="result" tabindex="-1"></div>
    """)

    async for obj in cell.inputs():
        result = await obj.call()
        body["#result"].set(t'<b>{result}</b>')

asyncio.run(main())
```

---

## Quick reference

| Operation | Method |
|---|---|
| Check buche is running | `is_available()` |
| Append HTML | `body.print(t'...')` |
| Replace contents | `body.set(t'...')` |
| Run JS | `body.exec(t'...')` |
| Load JS/CSS (embed in template) | `body.exec(Path(...))` / `body.print(t'<link href={Path(...)}>')` |
| Load JS/CSS (preload, process can exit) | `cell.map_files({"/x.css": Path("x.css")})` |
| Load JS/CSS (on demand, process stays alive) | handle `ResolveRequest` in `cell.inputs()`, call `obj.resolve_to(Path(...))` |
| Scope to selector | `body["#id"]` or `body[".cls"]` |
| Embed Python fn in JS | `{fn:js}` in a t-string (produces `embed(...)`) |
| Visual indicator | `event.indicate(fn, ...args)` in an onclick handler |
| Declare indicator target | `indicator-selector="..."` attribute on the element |
| Auto-focus on load | `id="prime-focus"` on the first focusable element |
| Configure cell behavior | `cell.configure(sticky=True)` / `cell.configure(background=True)` |
| Process callbacks | `async for obj in cell.inputs(): await obj.call()` (yields `Callback`, `ResolveRequest`, `Resize`, `RawMessage`) |
