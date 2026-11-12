"""riff-room: timed brainstorm rounds with Hermes as a teammate."""

from . import schemas, tools

_TOOLS = [
    (schemas.RIFF_NEW_BOARD, tools.riff_new_board),
    (schemas.RIFF_ADD_NOTES, tools.riff_add_notes),
    (schemas.RIFF_GET_BOARD, tools.riff_get_board),
    (schemas.RIFF_SORT, tools.riff_sort),
    (schemas.RIFF_REEL_IN, tools.riff_reel_in),
    (schemas.RIFF_EXPORT, tools.riff_export),
]


def register(ctx):
    for schema, handler in _TOOLS:
        ctx.register_tool(name=schema["name"], toolset="riff_room", schema=schema, handler=handler)
    ctx.register_hook("pre_llm_call", tools.on_pre_llm_call)
