# riff-room — agent notes

Hermes plugin (unified package) for timed brainstorm rounds. Target: Hermes ≥ 0.23.0. Canonical API docs are in the local Hermes checkout: `~/.hermes/hermes-agent/website/docs/developer-guide/plugins/index.md` and `desktop-plugin-sdk.md`; catalog rules in `plugins/catalog-submission.md`.

## Gate

Both must pass before any commit that changes plugin code:

```bash
hermes plugins validate . --install-deps
hermes plugins doctor . --ci
```

`provides_tools` / `provides_hooks` in `plugin.yaml` must list exactly what `register()` registers.

## Rules that are easy to break

- **Python handlers** take `(args: dict, **kwargs)`, return a JSON string, never raise.
- **Storage**: write only under `plugin_data_dir("riff-room")` (via `store.data_dir()`); atomic writes via `store.write_json`.
- **`dashboard/plugin_api.py` is imported standalone**, not as part of the package — it loads shared modules (`store.py`, later `board.py`) from the package root by path. Shared modules must therefore use no relative imports. Two copies of a module can be live (package import + route import), so cross-call safety must come from the file system (file locks), not module-level locks.
- **Never** assign into Hermes core modules or `sys.modules` (catalog rule 9; `no core override` check).
- **Desktop pane**: plain ESM, `jsx()` calls (no JSX syntax); imports only `@hermes/plugin-sdk`, `react`, `react/jsx-runtime`; `ctx.setInterval` / `ctx.addEventListener` / `ctx.onEvent`, never bare globals; colours only via `var(--ui-*)`; clipboard via `ctx.os.writeClipboard`.
- Live updates: `store.broadcast(event, payload)` → pane listens on `plugin.riff-room.<event>`; the pane must also poll, since events can drop.
