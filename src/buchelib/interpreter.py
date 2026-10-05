class Interpreter:
    async def eval(self, cell, command):
        raise NotImplementedError()

    async def on_error(self, cell, error):
        raise error

    async def handle_parse(self, prompt, message):
        pass

    async def handle_prompt_submit(self, prompt, message):
        # The `id` repeats the command's: the terminal uses it to give the
        # new cell the focus.
        cell = prompt.bridge.cell(echo=message.get("text"), id=message.get("id"))
        try:
            result = await self.eval(cell, message["text"])
            if result is not None:
                cell.body().print(result)
            cell.close()
        except Exception as exc:
            await self.on_error(cell, exc)
            cell.close(1)

    async def handle_prompt_close(self, prompt, message):
        raise SystemExit(0)

    async def __call__(self, prompt, message):
        msg_type = message.get("type")
        if msg_type == "command":
            # The terminal asks the driver to run a command: submit (the user
            # pressed Enter), parse (for a highlight answer), ...
            handler_name = {
                "submit": "handle_prompt_submit",
                "parse": "handle_parse",
            }.get(message.get("command"), "handle_command")
        elif msg_type == "parse":
            handler_name = "handle_parse"
        elif msg_type in ("signal", "close"):
            handler_name = "handle_prompt_close"
        else:
            handler_name = f"handle_{msg_type}"
        handler = getattr(self, handler_name, None)
        if handler is not None and callable(handler):
            return await handler(prompt, message)


class PythonInterpreter:
    async def eval(self, cell, command):
        result = eval(command)
        return result if result is None else str(result)
