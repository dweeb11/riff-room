# riff-room

Timed brainstorm rounds with Hermes as a teammate. You and the agent write sticky notes face-down during a timed burst; at time's up everything flips, then you sort, star and riff, and "reel it in" for a map plus one next step.

A unified Hermes plugin: agent tools + `pre_llm_call` hook + `/riff` command (Python), backend routes (`dashboard/plugin_api.py`), and a Desktop pane (`desktop/plugin.js`).

> Status: day-1 skeleton (diagnostic pane, one test tool, routes). Not usable yet.

## Develop

```bash
ln -s ~/projects/tools/riff-room ~/.hermes/plugins/riff-room
hermes plugins enable riff-room      # Python half (tools, routes)
hermes gateway restart               # routes mount at gateway start
# Desktop: Capabilities → Plugins → Rescan, then enable riff-room
```

Checks:

```bash
hermes plugins validate . --install-deps
hermes plugins doctor . --ci
```

## Disclosure

- No network calls, credentials or telemetry.
- Writes only under `<hermes home>/plugin-data/riff-room/`.
- Serves `/api/plugins/riff-room/*` on the gateway.

## License

MIT
