// riff-room desktop pane. Plain ESM, loaded uncompiled: jsx() calls only, SDK-only imports.
// Interim pane (day 2): lists this chat's boards and shows the user's view of the latest one,
// so the tools and routes can be checked end to end. The real board UI replaces it.

import { atom, host, queryClient, useQuery, useValue } from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'riff-room'
const $rest = atom(null) // ctx.rest, captured at register()
const muted = 'text-(--ui-text-tertiary)'

function Empty({ title, detail }) {
  return jsxs('div', {
    className: 'flex h-full flex-col gap-2 p-3 text-sm',
    children: [jsx('div', { className: 'font-medium', children: title }), jsx('div', { className: muted, children: detail })]
  })
}

function NoteRow({ note }) {
  const text = note.text ?? '▒▒▒ face-down'
  return jsxs('div', {
    className: 'flex gap-2 text-[0.75rem]',
    children: [
      jsx('span', { className: `w-8 shrink-0 font-mono ${muted}`, children: note.id }),
      jsx('span', {
        className: note.author === 'agent' ? 'text-(--ui-accent)' : '',
        children: `${note.starred ? '★ ' : ''}${text}`
      })
    ]
  })
}

function BoardPane() {
  const rest = useValue($rest)
  const storedId = useValue(host.state.focusedStoredSessionId)

  const list = useQuery({
    queryKey: [ID, 'boards', storedId],
    queryFn: () => rest(`/boards?session_id=${encodeURIComponent(storedId)}`),
    enabled: !!rest && !!storedId,
    refetchInterval: 3000,
    retry: false
  })
  const boardId = list.data?.boards?.[0]?.id
  const board = useQuery({
    queryKey: [ID, 'board', boardId],
    queryFn: () => rest(`/board/${boardId}`),
    enabled: !!rest && !!boardId,
    refetchInterval: 3000,
    retry: false
  })

  if (list.isError) {
    return jsx(Empty, {
      title: 'riff-room backend is off',
      detail: 'Enable the Python half (hermes plugins enable riff-room) and restart the gateway.'
    })
  }
  if (!storedId) return jsx(Empty, { title: 'riff-room', detail: 'Open a chat to see its board.' })
  if (!boardId) return jsx(Empty, { title: 'No board in this chat', detail: 'Ask Hermes to start a riff on a topic.' })

  const b = board.data
  if (!b) return jsx(Empty, { title: 'Loading…', detail: '' })
  const round = b.rounds[b.rounds.length - 1]

  return jsxs('div', {
    className: 'flex h-full flex-col gap-2 overflow-auto p-3 text-sm',
    children: [
      jsx('div', { className: 'font-medium', children: b.topic }),
      jsx('div', {
        className: `text-[0.6875rem] ${muted}`,
        children: `${b.id} · v${b.version} · ${round ? `round ${round.n} ${round.state}` : 'no rounds yet'} · ${b.notes.length} notes`
      }),
      ...b.notes.map(n => jsx(NoteRow, { key: n.id, note: n }))
    ]
  })
}

export default {
  id: ID,
  name: 'riff-room',
  register(ctx) {
    $rest.set((path, opts) => ctx.rest(path, opts))

    ctx.onEvent(`plugin.${ID}.board.changed`, () => {
      queryClient.invalidateQueries({ queryKey: [ID] })
    })

    ctx.register({
      id: 'pane',
      area: 'panes',
      title: 'riff-room',
      data: { placement: 'right', width: '380px' },
      render: () => jsx(BoardPane, {})
    })
  }
}
