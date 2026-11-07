// riff-room desktop pane. Plain ESM, loaded uncompiled: jsx() calls only, SDK-only imports.
// Shows the focused chat's board: a burst timer with pulse and chime, face-down cards,
// flip, stars, drag-sort between buckets, and a note composer that posts to the board.
// The timer is server-authoritative (round.ends_at); the pane only counts down to it.

import {
  atom,
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  host,
  icons,
  Input,
  queryClient,
  useQuery,
  useValue
} from '@hermes/plugin-sdk'
import { useRef, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'riff-room'
const NOTE_MAX = 140
const DURATIONS = [60, 180, 300]
const URGENT_MS = 30000 // the pulse speeds up in the last 30 s
const DRAG = 'application/x-riff-note'
const AUTHOR = { user: { color: 'var(--ui-yellow)', mark: 'you' }, agent: { color: 'var(--ui-accent)', mark: 'hermes' } }
const muted = { color: 'var(--ui-text-tertiary)' }

// Module state. ES modules outlive a hot-reload, so register() resets all of it.
let ctx = null
let seenRunning = new Set() // `${board}:${round}` this pane saw running: only those chime and announce
let flipAsked = new Set()
let handled = new Set()
let lastPulse = 0
let audio = null
const $now = atom(Date.now())
const $board = atom(null) // the board whose round this pane is timing
const $muted = atom(false)
const $duration = atom(180)

const boardKey = id => [ID, 'board', id]
const lastRound = b => b?.rounds?.[b.rounds.length - 1] ?? null
const withOffset = b => ({ ...b, _offset: Date.parse(b.server_now) - Date.now() })
const leftMs = (b, r) => Date.parse(r.ends_at) - (Date.now() + (b._offset || 0))
const clock = s => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`

async function call(path, fail, opts = {}) {
  try {
    return await ctx.rest(path, { method: 'POST', body: {}, ...opts })
  } catch (e) {
    host.notifyError(e, fail)
    return null
  }
}

// A route answered with the user's view of the board: show it at once.
function put(b) {
  const v = withOffset(b)
  queryClient.setQueryData(boardKey(v.id), v)
  observe(v)
  return v
}

function observe(b) {
  $board.set(b)
  const r = lastRound(b)
  if (!r) return
  const key = `${b.id}:${r.n}`
  if (r.state === 'running') seenRunning.add(key)
  else if (seenRunning.has(key) && !handled.has(key)) {
    handled.add(key)
    timesUp(b, r)
  }
}

function submit(b, text) {
  if (!host.composer.submit(b.session_id, text)) {
    host.notify({ kind: 'warning', message: "Open the board's chat so Hermes hears about it." })
  }
}

// ── audio: all generated, no files ──────────────────────────────────────────

function audioCtx() {
  if (!audio) {
    const AC = globalThis.AudioContext || globalThis.webkitAudioContext
    if (!AC) return null
    audio = new AC()
  }
  if (audio.state === 'suspended') audio.resume().catch(() => {})
  return audio
}

function tone(freq, start, dur, peak) {
  const a = audioCtx()
  if (!a) return
  const t = a.currentTime + start
  const osc = a.createOscillator()
  const gain = a.createGain()
  osc.type = 'sine'
  osc.frequency.value = freq
  gain.gain.setValueAtTime(0.0001, t)
  gain.gain.exponentialRampToValueAtTime(peak, t + 0.01)
  gain.gain.exponentialRampToValueAtTime(0.0001, t + dur)
  osc.connect(gain).connect(a.destination)
  osc.start(t)
  osc.stop(t + dur + 0.05)
}

const pulse = urgent => !$muted.get() && tone(urgent ? 660 : 440, 0, 0.08, urgent ? 0.06 : 0.035)

function chime() {
  if ($muted.get()) return
  tone(784, 0, 0.9, 0.12)
  tone(1175, 0.16, 1.1, 0.1)
  tone(1568, 0.32, 1.3, 0.07)
}

// ── round lifecycle ─────────────────────────────────────────────────────────

function tick() {
  const now = Date.now()
  $now.set(now)
  const b = $board.get()
  const r = lastRound(b)
  if (r?.state !== 'running') return
  const key = `${b.id}:${r.n}`
  const left = leftMs(b, r)
  if (left <= 0) {
    // First flip wins; a read after ends_at flips too, so a failed call heals on the next poll.
    if (!flipAsked.has(key)) {
      flipAsked.add(key)
      call(`/board/${b.id}/flip`, 'Flip failed').then(res => res && put(res.board))
    }
    return
  }
  const every = left <= URGENT_MS ? 500 : 1000
  if (now - lastPulse >= every) {
    lastPulse = now
    pulse(left <= URGENT_MS)
  }
}

async function timesUp(b, r) {
  chime()
  // Every window that saw the round asks; the board grants the message to exactly one.
  const res = await call(`/board/${b.id}/announce`, "Time's up message failed", { body: { key: `flip:${r.n}` } })
  if (!res?.claimed) return
  const notes = b.notes.filter(n => n.round === r.n).length
  const stars = b.notes.filter(n => n.starred).length
  submit(b, `⏱ Time's up: round ${r.n} flipped (${notes} notes, ${stars} stars). Sort and riff.`)
}

async function startRound(b) {
  audioCtx() // inside the click, so the browser lets the pulse play
  const d = $duration.get()
  const res = await call(`/board/${b.id}/round/start`, 'Could not start the round', { body: { duration_s: d } })
  if (!res) return
  const v = put(res)
  lastPulse = 0
  submit(v, `⏱ Round ${lastRound(v).n} burst started on '${v.topic}' (${clock(d)}). Add your face-down notes.`)
}

async function endRound(b) {
  const res = await call(`/board/${b.id}/flip`, 'Could not end the round')
  if (res) put(res.board)
}

async function moveNote(b, noteId, bucket) {
  if (b.notes.find(n => n.id === noteId)?.bucket === bucket) return
  const res = await call(`/board/${b.id}/move`, 'Could not move the note', { body: { note_id: noteId, bucket } })
  if (res) put(res)
}

async function starNote(b, n) {
  const res = await call(`/board/${b.id}/star`, 'Could not star the note', { body: { note_id: n.id, starred: !n.starred } })
  if (res) put(res)
}

async function editNote(b, n, text) {
  if (!text || text === n.text) return
  const res = await call(`/board/${b.id}/note/${n.id}`, 'Could not edit the note', { method: 'PATCH', body: { text } })
  if (res) put(res)
}

async function exportBoard(b) {
  const res = await call(`/board/${b.id}/export`, 'Export failed')
  if (!res) return
  const copied = await ctx.os.writeClipboard(res.markdown)
  host.notify({ kind: 'info', message: copied ? 'Exported and copied as markdown' : 'Exported as markdown', detail: res.path })
}

function cycleDuration() {
  const d = DURATIONS[(DURATIONS.indexOf($duration.get()) + 1) % DURATIONS.length]
  $duration.set(d)
  ctx.storage.set('duration', d)
}

function toggleMute() {
  $muted.set(!$muted.get())
  ctx.storage.set('muted', $muted.get())
}

// ── components ──────────────────────────────────────────────────────────────

function useBusy() {
  const [busy, setBusy] = useState(false)
  const run = fn => async () => {
    if (busy) return
    setBusy(true)
    try {
      await fn()
    } finally {
      setBusy(false)
    }
  }
  return [busy, run]
}

function Empty({ title, detail }) {
  return jsxs('div', {
    className: 'flex h-full flex-col gap-2 p-3 text-sm',
    children: [jsx('div', { className: 'font-medium', children: title }), jsx('div', { style: muted, children: detail })]
  })
}

function RoundChip({ b, r }) {
  useValue($now)
  if (!r) return jsx('span', { className: 'text-xs', style: muted, children: 'No rounds yet' })
  if (r.state !== 'running') return jsx('span', { className: 'text-xs', style: muted, children: `Round ${r.n} · flipped` })
  const s = Math.max(0, Math.ceil(leftMs(b, r) / 1000))
  return jsx('span', {
    className: 'text-xs font-medium',
    style: { color: s * 1000 <= URGENT_MS ? 'var(--ui-red)' : 'var(--ui-text-secondary)', fontVariantNumeric: 'tabular-nums' },
    children: `Round ${r.n} · Burst · ${clock(s)}`
  })
}

function Menu({ b, running }) {
  const isMuted = useValue($muted)
  return jsxs(DropdownMenu, {
    children: [
      jsx(DropdownMenuTrigger, {
        asChild: true,
        children: jsx(Button, { size: 'icon-xs', variant: 'ghost', 'aria-label': 'More', children: jsx(icons.MoreHorizontal, { size: 14 }) })
      }),
      jsxs(DropdownMenuContent, {
        align: 'end',
        children: [
          jsx(DropdownMenuItem, { disabled: running, onSelect: () => exportBoard(b), children: 'Export and copy markdown' }),
          jsx(DropdownMenuItem, { onSelect: toggleMute, children: isMuted ? 'Unmute sound' : 'Mute sound' })
        ]
      })
    ]
  })
}

function Header({ b, r, running, boards, onPick, offline }) {
  const duration = useValue($duration)
  const [busy, run] = useBusy()
  return jsxs('div', {
    className: 'flex flex-col gap-2 p-3',
    children: [
      boards.length > 1 &&
        jsx('select', {
          className: 'text-xs',
          style: { ...muted, background: 'transparent', border: 'none', outline: 'none' },
          value: b.id,
          onChange: e => onPick(e.target.value),
          children: boards.map(x => jsx('option', { value: x.id, children: x.topic }, x.id))
        }),
      jsx('div', { className: 'font-medium', style: { wordBreak: 'break-word' }, children: b.topic }),
      jsxs('div', {
        className: 'flex items-center gap-2',
        children: [
          jsx(RoundChip, { b, r }),
          jsx('div', { style: { flex: 1 } }),
          !running &&
            jsx(Button, { size: 'xs', variant: 'ghost', title: 'Burst length', onClick: cycleDuration, children: clock(duration) }),
          running
            ? jsx(Button, { size: 'xs', variant: 'secondary', disabled: busy, onClick: run(() => endRound(b)), children: 'End' })
            : jsx(Button, { size: 'xs', disabled: busy, onClick: run(() => startRound(b)), children: 'Start' }),
          jsx(Menu, { b, running })
        ]
      }),
      offline && jsx('div', { className: 'text-xs', style: muted, children: 'Reconnecting…' })
    ]
  })
}

function EditBox({ n, onDone }) {
  const [text, setText] = useState(n.text)
  const done = useRef(false) // Enter or Escape unmounts the box, which fires blur too
  const finish = save => {
    if (done.current) return
    done.current = true
    onDone(save ? text.trim() : null)
  }
  return jsx(Input, {
    autoFocus: true,
    value: text,
    maxLength: NOTE_MAX,
    onChange: e => setText(e.target.value),
    onBlur: () => finish(true),
    onKeyDown: e => {
      if (e.key === 'Enter' && !e.nativeEvent.isComposing) finish(true)
      if (e.key === 'Escape') finish(false)
    }
  })
}

function Card({ b, n }) {
  const [editing, setEditing] = useState(false)
  const { color, mark } = AUTHOR[n.author]
  const hidden = n.text == null // the other side's face-down card back
  const canDrag = !hidden && !n.dimmed && !editing
  const tint = pct => `color-mix(in srgb, ${color} ${pct}%, transparent)`
  return jsxs('div', {
    draggable: canDrag,
    onDragStart: e => {
      e.dataTransfer.setData(DRAG, n.id)
      e.dataTransfer.effectAllowed = 'move'
    },
    onDoubleClick: () => n.author === 'user' && !n.dimmed && setEditing(true),
    title: n.author === 'user' && !n.dimmed ? 'Double-click to edit' : undefined,
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 4,
      minHeight: 56,
      padding: '6px 8px',
      borderRadius: 6,
      fontSize: '0.75rem',
      lineHeight: 1.35,
      background: hidden ? `repeating-linear-gradient(135deg, ${tint(20)} 0 6px, ${tint(8)} 6px 12px)` : tint(13),
      boxShadow: `inset 2px 0 0 ${color}`,
      border: n.face_down && !hidden ? `1px dashed ${tint(60)}` : '1px solid transparent',
      opacity: n.dimmed ? 0.45 : 1,
      cursor: canDrag ? 'grab' : 'default'
    },
    children: [
      editing
        ? jsx(EditBox, { n, onDone: text => (setEditing(false), text && editNote(b, n, text)) })
        : jsx('div', {
            style: hidden ? muted : { color: 'var(--ui-text-primary)', wordBreak: 'break-word' },
            children: hidden ? 'face-down' : n.text
          }),
      jsxs('div', {
        className: 'flex items-center gap-2',
        style: { ...muted, fontSize: '0.6875rem', marginTop: 'auto' },
        children: [
          jsx('span', { style: { color }, children: mark }),
          jsx('span', { children: n.id }),
          n.spark_of && jsx('span', { title: `Sparked by ${n.spark_of}`, children: `↳ ${n.spark_of}` }),
          n.face_down && !hidden && jsx('span', { title: 'Hidden from Hermes until the flip', children: 'face-down' }),
          jsx('span', { style: { flex: 1 } }),
          !n.face_down &&
            jsx('button', {
              type: 'button',
              title: n.starred ? 'Unstar' : 'Star',
              onClick: () => starNote(b, n),
              style: { color: n.starred ? 'var(--ui-orange)' : 'var(--ui-text-quaternary)', fontSize: '0.875rem', lineHeight: 1 },
              children: n.starred ? '★' : '☆'
            })
        ]
      })
    ]
  })
}

function Section({ b, title, bucket, notes, hint }) {
  const [over, setOver] = useState(false)
  const droppable = bucket !== undefined
  return jsxs('section', {
    onDragOver: e => {
      if (droppable && e.dataTransfer.types.includes(DRAG)) {
        e.preventDefault()
        setOver(true)
      }
    },
    onDragLeave: e => !e.currentTarget.contains(e.relatedTarget) && setOver(false),
    onDrop: e => {
      setOver(false)
      const id = droppable && e.dataTransfer.getData(DRAG)
      if (!id) return
      e.preventDefault()
      moveNote(b, id, bucket)
    },
    style: {
      padding: 6,
      borderRadius: 8,
      outline: `1px dashed ${over ? 'var(--ui-accent)' : 'transparent'}`,
      background: over ? 'color-mix(in srgb, var(--ui-accent) 6%, transparent)' : undefined
    },
    children: [
      jsxs('div', {
        className: 'flex items-center gap-2 text-xs',
        style: { ...muted, marginBottom: 4 },
        children: [jsx('span', { className: 'font-medium', children: title }), notes.length > 0 && jsx('span', { children: notes.length })]
      }),
      notes.length
        ? jsx('div', {
            style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 6 },
            children: notes.map(n => jsx(Card, { b, n }, n.id))
          })
        : jsx('div', { className: 'text-xs', style: { ...muted, padding: '4px 2px' }, children: hint })
    ]
  })
}

function Composer({ b, running }) {
  const [text, setText] = useState('')
  const send = async () => {
    const t = text.trim()
    if (!t) return
    setText('')
    const res = await call(`/board/${b.id}/notes`, 'Note not added', { body: { text: t } })
    if (res) put(res.board)
    else setText(t)
  }
  return jsxs('div', {
    className: 'flex items-center gap-2 p-3',
    style: { borderTop: '1px solid var(--ui-stroke-tertiary)' },
    children: [
      jsx(Input, {
        value: text,
        maxLength: NOTE_MAX,
        placeholder: running ? 'Face-down note, Enter' : 'Add a note, Enter',
        onChange: e => setText(e.target.value),
        onKeyDown: e => {
          if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
            e.preventDefault()
            send()
          }
        }
      }),
      text.length > 100 && jsx('span', { className: 'text-xs', style: muted, children: NOTE_MAX - text.length })
    ]
  })
}

function Board({ b, boards, onPick, offline }) {
  const r = lastRound(b)
  const running = r?.state === 'running'
  const live = b.notes.filter(n => !n.dimmed)
  const parked = b.notes.filter(n => n.dimmed)
  return jsxs('div', {
    className: 'flex h-full flex-col text-sm',
    style: { minHeight: 0 },
    onPointerDown: () => !$muted.get() && running && audioCtx(), // re-arm sound after an app restart
    children: [
      jsx(Header, { b, r, running, boards, onPick, offline }),
      jsxs('div', {
        className: 'flex flex-col gap-2 overflow-auto',
        style: { flex: 1, minHeight: 0, padding: '0 6px 6px' },
        children: [
          jsx(Section, { b, title: 'Unsorted', bucket: null, notes: live.filter(n => !n.bucket), hint: 'New notes land here.' }),
          ...b.buckets.map(k =>
            jsx(Section, { b, title: k.name, bucket: k.id, notes: live.filter(n => n.bucket === k.id), hint: 'Drag notes here.' }, k.id)
          ),
          parked.length > 0 && jsx(Section, { b, title: 'Parked', notes: parked }, 'parked')
        ]
      }),
      jsx(Composer, { b, running })
    ]
  })
}

function BoardPane() {
  const storedId = useValue(host.state.focusedStoredSessionId)
  const [pick, setPick] = useState(null)

  const list = useQuery({
    queryKey: [ID, 'boards', storedId],
    queryFn: () => ctx.rest(`/boards?session_id=${encodeURIComponent(storedId)}`),
    enabled: !!storedId,
    refetchInterval: 5000,
    retry: false
  })
  const boards = list.data?.boards ?? []
  const boardId = boards.some(x => x.id === pick) ? pick : boards[0]?.id
  const board = useQuery({
    queryKey: boardKey(boardId),
    queryFn: () =>
      ctx.rest(`/board/${boardId}`).then(b => {
        const v = withOffset(b)
        observe(v)
        return v
      }),
    enabled: !!boardId,
    refetchInterval: 2000, // card backs trickle in by reveal_at, which no event announces
    retry: false
  })

  if (!storedId) return jsx(Empty, { title: 'riff-room', detail: 'Open a chat to see its board.' })
  if (list.isError && !list.data) {
    return jsx(Empty, {
      title: 'riff-room backend is off',
      detail: 'Enable the Python half (hermes plugins enable riff-room) and restart the gateway.'
    })
  }
  if (!list.data) return jsx(Empty, { title: 'riff-room', detail: 'Loading…' })
  if (!boardId) return jsx(Empty, { title: 'No board in this chat', detail: 'Ask Hermes to start a riff on a topic.' })
  if (!board.data) return jsx(Empty, { title: 'riff-room', detail: board.isError ? 'Could not load the board.' : 'Loading…' })
  return jsx(Board, { b: board.data, boards, onPick: setPick, offline: list.isError || board.isError })
}

export default {
  id: ID,
  name: 'riff-room',
  register(c) {
    ctx = c
    seenRunning = new Set()
    flipAsked = new Set()
    handled = new Set()
    lastPulse = 0
    audio = null
    $board.set(null)
    $muted.set(!!c.storage.get('muted', false))
    const d = c.storage.get('duration', 180)
    $duration.set(DURATIONS.includes(d) ? d : 180)

    c.setInterval(tick, 250)
    c.onDispose(() => {
      audio?.close().catch(() => {})
      audio = null
    })
    c.onEvent(`plugin.${ID}.board.changed`, () => {
      queryClient.invalidateQueries({ queryKey: [ID] })
    })

    c.register({
      id: 'pane',
      area: 'panes',
      title: 'riff-room',
      data: { placement: 'right', width: '380px' },
      render: () => jsx(BoardPane, {})
    })
  }
}
