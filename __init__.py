"""riff-room: timed brainstorm rounds with Hermes as a teammate."""

from . import schemas, tools


def register(ctx):
    ctx.register_tool(name="riff_ping", toolset="riff_room", schema=schemas.RIFF_PING, handler=tools.riff_ping)
