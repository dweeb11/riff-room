# riff-room

Timed brainstorm rounds with Hermes as a teammate. You and the agent write sticky notes face-down during a timed burst; at time's up everything flips, then you sort, star and riff, and "reel it in" for a map plus one next step.

A unified Hermes plugin: six agent tools (Python), backend routes (`dashboard/plugin_api.py`), and a Desktop pane (`desktop/plugin.js`).

> Status: early. The full round works in code and tests, but has not yet been played end to end in Desktop.

## What's in it

- **Agent tools:** `riff_new_board`, `riff_add_notes`, `riff_get_board`, `riff_sort`, `riff_reel_in`, `riff_export`.
- **Launcher:** a **Riff** button in the title bar (and "Riff: open the brainstorm board" in ⌘K) opens the pane and puts the caret in it. With no board yet, the pane asks for a topic and Hermes sets one up.
- **Pane:** burst timer with a chime at time's up, face-down cards that flip, stars, drag-sort into buckets, a note field at the top (highlighted until your first note on a board), and markdown export.
- **No anchoring:** during a burst, neither side sees the other's note text until the flip.

Not built yet: the reel-in map view in the pane, and a hook that tells the agent when a round flips (today it only knows the board's state when it calls `riff_get_board`).

## Develop

```bash
ln -s ~/projects/riff-room ~/.hermes/plugins/riff-room   # once; skip if the link exists
hermes plugins enable riff-room      # Python half (tools, routes)
hermes gateway restart               # routes mount at gateway start
# Desktop: Capabilities → Plugins → Rescan, then enable riff-room
```

Desktop runs a copy of `desktop/plugin.js`. After pulling pane changes, Rescan (or restart the app), or it keeps running the old pane.

Checks (all must pass before committing plugin code):

```bash
hermes plugins validate . --install-deps
hermes plugins doctor . --ci
hermes --run-module unittest discover -s tests
```

## Disclosure

- No network calls, credentials or telemetry.
- Writes only under `<hermes home>/plugin-data/riff-room/`.
- Serves `/api/plugins/riff-room/*` on the gateway.

## License

MIT
