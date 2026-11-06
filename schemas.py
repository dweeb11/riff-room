"""Tool schemas: what the model reads."""

_BOARD_ID = {"type": "string", "description": "Board id, e.g. b_1a2b3c4d."}

RIFF_NEW_BOARD = {
    "name": "riff_new_board",
    "description": (
        "Create a riff-room brainstorm board for this chat: a topic plus optional buckets "
        "(columns to sort ideas into). The board shows in the riff-room pane. "
        "Use when the user wants to brainstorm or riff on something."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "What the brainstorm is about (≤200 chars)."},
            "buckets": {"type": "array", "items": {"type": "string"},
                        "description": "Optional bucket names, e.g. [\"combat\", \"exploration\"]."},
        },
        "required": ["topic"],
    },
}

RIFF_ADD_NOTES = {
    "name": "riff_add_notes",
    "description": (
        "Add your own sticky notes to a board (≤140 chars each, up to 12 per call). During a "
        "running burst they go in face-down and their card backs trickle onto the board; the "
        "user's face-down notes stay hidden from you until the flip, so write without waiting "
        "for theirs. After the flip, add one or two ideas at a time and link a note that builds "
        "on another with spark_of."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "board_id": _BOARD_ID,
            "notes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "The idea, ≤140 chars."},
                        "spark_of": {"type": "string", "description": "Optional id of the note this builds on."},
                    },
                    "required": ["text"],
                },
            },
        },
        "required": ["board_id", "notes"],
    },
}

RIFF_GET_BOARD = {
    "name": "riff_get_board",
    "description": (
        "Read a board: round state, time left, buckets and notes with ids, stars (★, set by the "
        "user) and spark links. The user's face-down notes show only as a count until the flip. "
        "view=summary (default) is compact text; view=full is JSON."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "board_id": _BOARD_ID,
            "view": {"type": "string", "enum": ["summary", "full"]},
        },
        "required": ["board_id"],
    },
}

RIFF_SORT = {
    "name": "riff_sort",
    "description": (
        "Sort face-up notes into buckets, optionally creating buckets first, and dim (park) "
        "notes that lost energy. bucket may be a bucket id or name; null moves a note back to "
        "unsorted. Sorting is the only phase for critique."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "board_id": _BOARD_ID,
            "moves": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "note_id": {"type": "string"},
                        "bucket": {"type": ["string", "null"]},
                    },
                    "required": ["note_id", "bucket"],
                },
            },
            "new_buckets": {"type": "array", "items": {"type": "string"}},
            "dim": {"type": "array", "items": {"type": "string"}, "description": "Note ids to park."},
        },
        "required": ["board_id"],
    },
}

RIFF_REEL_IN = {
    "name": "riff_reel_in",
    "description": (
        "Only when the user says to reel it in: record the map (named clusters of note ids), "
        "the notes with the most heat, and exactly one concrete next step. The pane switches "
        "to the map view."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "board_id": _BOARD_ID,
            "clusters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "note_ids": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["name", "note_ids"],
                },
            },
            "heat_note_ids": {"type": "array", "items": {"type": "string"}},
            "next_step": {"type": "string", "description": "One concrete next step."},
        },
        "required": ["board_id", "clusters", "next_step"],
    },
}

RIFF_EXPORT = {
    "name": "riff_export",
    "description": "Export a board as markdown (buckets, ★ stars, parked ideas, the reel-in map). Returns the file path.",
    "parameters": {"type": "object", "properties": {"board_id": _BOARD_ID}, "required": ["board_id"]},
}
