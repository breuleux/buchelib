class Interpreter:
    async def eval(self, cell, command):
        raise NotImplementedError()

    async def on_error(self, cell, error):
        raise error

    async def handle_parse(self, prompt, message):
        pass

    async def handle_prompt_submit(self, prompt, message):
        cell = prompt.bridge.cell(echo=message.get("echo_html", None))
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
        handler_name = f"handle_{msg_type}"
        handler = getattr(self, handler_name, None)
        if handler is not None and callable(handler):
            return await handler(prompt, message)


class PythonInterpreter:
    async def eval(self, cell, command):
        result = eval(command)
        return result if result is None else str(result)
