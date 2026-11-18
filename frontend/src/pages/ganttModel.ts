// Модель диаграммы Ганта в виде, привычном по 1С («График этапов производства»):
// строка линии со сводной полосой всех этапов и вложенные строки этапов под ней.
// Полосы режутся по нерабочему времени линии — видно, в какие смены идёт этап.

import type { TimelineGroup, TimelineItem } from 'vis-timeline/standalone'

import type { Schedule, ScheduleTask } from '../api'

const HOUR = 3_600_000
const num = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const WEEKDAYS = ['воскресенье', 'понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота']
const MONTHS = [
  'январь',
  'февраль',
  'март',
  'апрель',
  'май',
  'июнь',
  'июль',
  'август',
  'сентябрь',
  'октябрь',
  'ноябрь',
  'декабрь',
]

export type Segment = { start: number; end: number }

/** «КЛ00-1735.1.1» → { order: «1735», stage: «1735.1.1» } */
export function shortNumber(number: string) {
  const stage = number.replace(/^[^-]*-0*/, '')
  return { order: stage.split('.')[0], stage }
}

/** Отрезки [start, end) без нерабочего времени линии. off — отсортированные интервалы простоя. */
export function workingSegments(start: number, end: number, off: Segment[]): Segment[] {
  const out: Segment[] = []
  let cursor = start
  for (const o of off) {
    if (o.end <= cursor) continue
    if (o.start >= end) break
    if (o.start > cursor) out.push({ start: cursor, end: Math.min(o.start, end) })
    cursor = Math.max(cursor, o.end)
    if (cursor >= end) break
  }
  if (cursor < end) out.push({ start: cursor, end })
  return out.filter((s) => s.end - s.start >= 60_000)
}

export function offByLine(data: Schedule): Map<string, Segment[]> {
  const map = new Map<string, Segment[]>()
  for (const o of data.off) {
    const list = map.get(o.line_code) ?? []
    list.push({ start: new Date(o.start).getTime(), end: new Date(o.end).getTime() })
    map.set(o.line_code, list)
  }
  for (const list of map.values()) list.sort((a, b) => a.start - b.start)
  return map
}

export const esc = (s: string) =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

function marks(t: ScheduleTask) {
  const stm = t.stm ? '<span class="mk-stm" title="СТМ — заказ по письму клиента">СТМ</span> ' : ''
  return stm + startMarks(t)
}

function startMarks(t: ScheduleTask) {
  if (t.status === 'Начат') return '<span class="mk-started" title="Начат в 1С — место зафиксировано">▶</span> '
  return t.line_locked ? '<span class="mk-pinned" title="Очередь линии задана вручную">📍</span> ' : ''
}

export function buildGroups(data: Schedule, expanded: Set<string>): TimelineGroup[] {
  const groups: TimelineGroup[] = []
  data.lines.forEach((l, i) => {
    const tasks = data.tasks
      .filter((t) => t.line_code === l.code && t.start)
      .sort((a, b) => a.start!.localeCompare(b.start!))
    const id = `line:${l.code}`
    groups.push({
      id,
      order: i,
      content: `<span class="line-title">${esc(l.title ?? l.code)}</span>`,
      className: 'line-row',
      ...(tasks.length ? { nestedGroups: tasks.map((t) => `task:${t.id}`), showNested: expanded.has(id) } : {}),
    })
    tasks.forEach((t, k) => {
      const warn = t.warnings.length ? ' warn' : ''
      groups.push({
        id: `task:${t.id}`,
        order: k,
        treeLevel: 1,
        content: `<span class="task-title${warn}">${marks(t)}${shortNumber(t.number).order}: ${esc(t.item)}, ${num.format(t.qty)} шт</span>`,
        className: `task-row${warn}`,
      } as TimelineGroup) // treeLevel есть в vis-timeline, но не в его типах
    })
  })
  return groups
}

export type SegmentRef = { task: ScheduleTask; segment: Segment }

export function buildItems(
  data: Schedule,
  tooltip: (t: ScheduleTask) => string,
): { items: TimelineItem[]; refs: Map<string, SegmentRef> } {
  const off = offByLine(data)
  const items: TimelineItem[] = []
  const refs = new Map<string, SegmentRef>()

  for (const [line, list] of off) {
    list.forEach((o, i) =>
      items.push({
        id: `off:${line}:${i}`,
        group: `line:${line}`,
        start: new Date(o.start),
        end: new Date(o.end),
        type: 'background',
        className: 'off',
        content: '',
      }),
    )
  }

  for (const t of data.tasks) {
    if (!t.line_code || !t.start || !t.end) continue
    const segments = workingSegments(new Date(t.start).getTime(), new Date(t.end).getTime(), off.get(t.line_code) ?? [])
    const title = tooltip(t)
    const started = t.status === 'Начат'
    const state = [
      t.warnings.length ? 'warn' : '',
      started ? 'started' : '',
      t.line_locked && !started ? 'pinned' : '',
      t.stm ? 'stm' : '',
    ]
      .filter(Boolean)
      .join(' ')
    const label = shortNumber(t.number).stage
    segments.forEach((s, k) => {
      // строка линии: первый час первого отрезка — переналадка
      let from = s.start
      if (k === 0 && t.changeover) {
        const co = Math.min(s.start + HOUR, s.end)
        items.push({
          id: `co:${t.id}`,
          group: `line:${t.line_code}`,
          start: new Date(s.start),
          end: new Date(co),
          content: '',
          title: `Переналадка перед ${label}`,
          className: 'changeover',
          editable: false,
        })
        from = co
      }
      if (s.end > from) {
        items.push({
          id: `L:${t.id}:${k}`,
          group: `line:${t.line_code}`,
          start: new Date(from),
          end: new Date(s.end),
          content: label,
          title,
          className: `seg-line ${state}`,
          editable: false,
        })
      }
      const id = `T:${t.id}:${k}`
      refs.set(id, { task: t, segment: s })
      items.push({
        id,
        group: `task:${t.id}`,
        start: new Date(s.start),
        end: new Date(s.end),
        content: '',
        title,
        className: `seg-task ${state}`,
        // начатый этап не двигается; остальные — перетаскиванием меняют место в очереди своей линии
        editable: started ? false : { updateTime: true, updateGroup: false, remove: false },
      })
    })
  }
  return { items, refs }
}

type Moment = { valueOf(): number }

const WEEKDAYS_SHORT = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб']

/** Подписи шкалы как в 1С: «17 вторник» (при мелком масштабе «17 вт»), часы — «08:00», сверху — «ноябрь 2026». */
export const timeAxisFormat = (longDays: () => boolean) => ({
  minorLabels: (date: Moment, scale: string) => {
    const d = new Date(date.valueOf())
    if (scale === 'day' || scale === 'weekday')
      return `${d.getDate()} ${(longDays() ? WEEKDAYS : WEEKDAYS_SHORT)[d.getDay()]}`
    if (scale === 'hour' || scale === 'minute')
      return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
    if (scale === 'month') return MONTHS[d.getMonth()]
    if (scale === 'year') return String(d.getFullYear())
    return String(d.getDate())
  },
  majorLabels: (date: Moment, scale: string) => {
    const d = new Date(date.valueOf())
    if (scale === 'hour' || scale === 'minute') return `${d.getDate()} ${WEEKDAYS[d.getDay()]}, ${MONTHS[d.getMonth()]}`
    if (scale === 'month' || scale === 'year') return String(d.getFullYear())
    return `${MONTHS[d.getMonth()]} ${d.getFullYear()}`
  },
})
