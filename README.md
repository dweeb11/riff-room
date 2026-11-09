# riff-room

Timed brainstorm rounds with Hermes as a teammate. You and the agent write sticky notes face-down during a timed burst; at time's up everything flips, then you sort, star and riff, and "reel it in" for a map plus one next step.

A unified Hermes plugin: six agent tools (Python), backend routes (`dashboard/plugin_api.py`), and a Desktop pane (`desktop/plugin.js`).

> Status: early. The full round, including the launch-to-first-note flow (launcher, board above chat, burst-only note field), has been played in Desktop.

## What's in it

- **Agent tools:** `riff_new_board`, `riff_add_notes`, `riff_get_board`, `riff_sort`, `riff_reel_in`, `riff_export`.
- **Launcher:** a **Riff** button in the title bar (and "Riff: open the brainstorm board" in ⌘K) opens the pane and puts the caret in it. With no board yet, the pane asks for a topic and Hermes sets one up.
- **Pane:** burst timer with a chime at time's up, face-down cards that flip, stars, drag-sort into buckets, a note field at the top that is open only during a burst (highlighted until your first note on a board; an idea still being typed at time's up can be added or discarded), a **Reel it in** button after a flip (it asks Hermes in chat; the map then shows in the pane: the next step, the notes with the most heat, and the named clusters, with a Map/Board toggle), and markdown export. Pressing Start moves the board into the main area above the chat, which stays live below it as a strip; **Back to chat** (or closing the tab) puts it back in the side pane.
- **No anchoring:** during a burst, neither side sees the other's note text until the flip.

Not built yet: a hook that tells the agent when a round flips. Today the pane posts a time's-up message to the board's chat when that chat is open; otherwise the agent only learns of the flip when it calls `riff_get_board`.

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
