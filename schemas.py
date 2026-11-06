"""Tool schemas: what the model reads."""

RIFF_PING = {
    "name": "riff_ping",
    "description": (
        "Diagnostic for the riff-room plugin. Records the calling session id and "
        "pings the riff-room desktop pane. Call only when the user asks to test riff-room."
    ),
    "parameters": {"type": "object", "properties": {}},
}
