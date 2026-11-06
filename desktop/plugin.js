// riff-room desktop pane. Plain ESM, loaded uncompiled: jsx() calls only, SDK-only imports.
// Day-1 skeleton: a diagnostic pane that settles the spec's VERIFY items
// (session ids, plugin event delivery, host.composer.submit).

import { atom, Button, host, useQuery, useValue, queryClient } from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'riff-room'
const $events = atom([]) // last few plugin.riff-room.* events seen by this window
const $restCtx = atom(null) // ctx.rest, captured at register()

const muted = 'text-(--ui-text-tertiary)'

function Row({ label, value, ok }) {
  return jsxs('div', {
    className: 'flex gap-2 font-mono text-[0.6875rem]',
    children: [
      jsx('span', { className: `w-28 shrink-0 ${muted}`, children: label }),
      jsx('span', {
        className: ok === false ? 'text-(--ui-yellow)' : ok ? 'text-(--ui-accent)' : '',
        children: value ?? '—'
      })
    ]
  })
}

function VerifyPane() {
  const rest = useValue($restCtx)
  const runtimeId = useValue(host.state.focusedSessionId)
  const storedId = useValue(host.state.focusedStoredSessionId)
  const events = useValue($events)

  const verify = useQuery({
    queryKey: [ID, 'verify'],
    queryFn: () => rest('/verify'),
    enabled: !!rest,
    refetchInterval: 3000,
    retry: false
  })

  if (verify.isError) {
    return jsxs('div', {
      className: 'flex h-full flex-col gap-2 p-3 text-sm',
      children: [
        jsx('div', { className: 'font-medium', children: 'riff-room backend is off' }),
        jsx('div', {
          className: muted,
          children: 'Enable the Python half (hermes plugins enable riff-room) and restart the gateway.'
        })
      ]
    })
  }

  const toolSid = verify.data?.last_tool_ping?.session_id
  const match = toolSid ? (toolSid === storedId ? 'stored' : toolSid === runtimeId ? 'runtime' : 'neither') : null

  const pingRoute = () =>
    rest('/ping', { method: 'POST', body: { storedId, runtimeId } }).catch(e => host.notifyError(e, 'ping failed'))

  const submitTest = () => {
    const sent = host.composer.submit(storedId, 'riff-room day-1 check: please call the riff_ping tool once.')
    host.notify({ kind: sent ? 'info' : 'warning', message: `composer.submit returned ${sent}` })
  }

  return jsxs('div', {
    className: 'flex h-full flex-col gap-3 overflow-auto p-3 text-sm',
    children: [
      jsx('div', { className: 'font-medium', children: 'riff-room · day-1 verify' }),
      jsxs('div', {
        className: 'flex flex-col gap-1',
        children: [
          jsx(Row, { label: 'pane stored id', value: storedId }),
          jsx(Row, { label: 'pane runtime id', value: runtimeId }),
          jsx(Row, { label: 'tool session_id', value: toolSid }),
          jsx(Row, { label: 'tool id matches', value: match, ok: match ? match !== 'neither' : undefined })
        ]
      }),
      jsxs('div', {
        className: 'flex flex-wrap gap-2',
        children: [
          jsx(Button, { size: 'sm', variant: 'outline', onClick: pingRoute, children: 'Ping via route' }),
          jsx(Button, { size: 'sm', variant: 'outline', onClick: submitTest, disabled: !storedId, children: 'Submit test message' })
        ]
      }),
      jsx('div', { className: `text-[0.6875rem] ${muted}`, children: `events received (${events.length})` }),
      jsx('div', {
        className: 'flex flex-col gap-1',
        children: events.map((e, i) =>
          jsx(Row, { key: i, label: `${e.origin} ${e.seenAt}`, value: e.session_id ?? e.echo?.storedId ?? '' })
        )
      })
    ]
  })
}

export default {
  id: ID,
  name: 'riff-room',
  register(ctx) {
    $restCtx.set((path, opts) => ctx.rest(path, opts))

    ctx.onEvent(`plugin.${ID}.ping`, ({ payload }) => {
      const seenAt = new Date().toLocaleTimeString()
      $events.set([{ ...payload, seenAt }, ...$events.get()].slice(0, 8))
      queryClient.invalidateQueries({ queryKey: [ID, 'verify'] })
    })

    ctx.register({
      id: 'pane',
      area: 'panes',
      title: 'riff-room',
      data: { placement: 'right', width: '380px' },
      render: () => jsx(VerifyPane, {})
    })
  }
}
