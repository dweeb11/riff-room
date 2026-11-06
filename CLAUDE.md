# riff-room — agent notes

Hermes plugin (unified package) for timed brainstorm rounds. Target: Hermes ≥ 0.23.0. Canonical API docs are in the local Hermes checkout: `~/.hermes/hermes-agent/website/docs/developer-guide/plugins/index.md` and `desktop-plugin-sdk.md`; catalog rules in `plugins/catalog-submission.md`.

## Gate

Both must pass before any commit that changes plugin code:

```bash
hermes plugins validate . --install-deps
hermes plugins doctor . --ci
hermes --run-module unittest discover -s tests   # Hermes runtime: board + tools + routes
```

`python3 -m unittest discover -s tests` runs the board tests alone (integration tests skip without FastAPI). No pytest: the Hermes runtime doesn't ship it.

`provides_tools` / `provides_hooks` in `plugin.yaml` must list exactly what `register()` registers.

## Rules that are easy to break

- **Python handlers** take `(args: dict, **kwargs)`, return a JSON string, never raise.
- **Storage**: write only under `plugin_data_dir("riff-room")` (via `store.data_dir()`); atomic writes via `store.write_json`.
- **`dashboard/plugin_api.py` is imported standalone**, not as part of the package — it loads `store.py` from the package root by path, and `store.py` loads `board.py` the same way. Shared modules must therefore use no relative imports. Two copies of a module can be live (package import + route import), so cross-call safety must come from the file system (file locks), not module-level locks.
- **Never** assign into Hermes core modules or `sys.modules` (catalog rule 9; `no core override` check).
- **Desktop pane**: plain ESM, `jsx()` calls (no JSX syntax); imports only `@hermes/plugin-sdk`, `react`, `react/jsx-runtime`; `ctx.setInterval` / `ctx.addEventListener` / `ctx.onEvent`, never bare globals; colours only via `var(--ui-*)`; clipboard via `ctx.os.writeClipboard`.
- **Never return a raw board** from a tool or route: always `board.view(b, viewer)` or `board.summary`. That is where the no-anchoring rule (face-down text hidden from the other author) lives.
- Live updates: `store.broadcast(event, payload)` → pane listens on `plugin.riff-room.<event>`; the pane must also poll, since events can drop.

## Verified facts (Hermes 0.23.0)

- A tool handler's `session_id` kwarg is the **stored** session id (the `hermes --resume` id, e.g. `local-<hash>`), and `task_id` equals it in a top-level turn. Bind boards to it; the pane matches with `host.state.focusedStoredSessionId`. (Checked 2026-11-05 via `riff_ping` in a CLI turn and a Desktop turn on macOS — same `local-<hash>` stored id.)
- Desktop runs a **copy** of `desktop/plugin.js` (`~/.hermes/desktop-plugins/riff-room/`), refreshed only on Rescan or app restart; a git or pip update leaves the old pane running against the new routes. A symlinked checkout hot-reloads. (Seen 2026-11-06 on the Mac: day-1 pane, "backend is off".)
- Tool text must only promise pane controls that exist on this branch; the agent repeats it to the user verbatim.
- Broadcasts from `hermes chat` reach no Desktop window (documented); only gateway-hosted turns and routes reach the pane.
- Plugin routes on the local gateway reject unauthenticated curl (401) — test routes in-process, not over HTTP.
