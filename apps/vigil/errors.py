"""Vigil's field errors, in words Jackil can show."""


def error_lines(errors: dict) -> list[str]:
    """Vigil's per-field error lists as plain sentences, in the order it gives them.

    ``{"device_type": ["Not a valid choice."]}`` becomes that one sentence; an
    error under a name we have no field for still shows rather than being lost.
    """
    lines: list[str] = []
    for values in (errors or {}).values():
        for value in values if isinstance(values, list) else [values]:
            text = str(value).strip()
            if text and text not in lines:
                lines.append(text)
    return lines


def error_message(message: str, errors: dict) -> str:
    """One sentence naming what Vigil objected to.

    Its 400 body keeps the reasons in per-field lists and leaves ``error``
    blank, so the first reason is the most a page has to say.
    """
    if message.strip():
        return message
    lines = error_lines(errors)
    return lines[0] if lines else "Bad Request"
