import 'vis-timeline/styles/vis-timeline-graph2d.min.css'
import './gantt.css'

import { Alert, Badge, Box, Button, Group, ScrollArea, Select, Stack, Switch, Table, Text, Title, Tooltip } from '@mantine/core'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Timeline, type TimelineOptions } from 'vis-timeline/standalone'

import { scheduleApi, type Schedule, type ScheduleTask } from '../api'
import { buildGroups, buildItems, esc, timeAxisFormat } from './ganttModel'

const DAY = 86_400_000
const num = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const isoDate = (d: Date) => d.toISOString().slice(0, 10)
const fmt = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—'
const fmtDate = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString('ru-RU') : '—')

// Время на сервере — местное, без часового пояса
function localIso(d: Date) {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:00`
}

function tooltip(t: ScheduleTask) {
  const lines = [
    `<b>${esc(t.number)}</b> · ${esc(t.item)}`,
    `${num.format(t.qty)} шт · ${t.hours} ч${t.changeover ? ' (с переналадкой 1 ч)' : ''}`,
    ...(t.qty_done ? [`Выпущено ${num.format(t.qty_done)} из ${num.format(t.qty_plan ?? 0)}`] : []),
    `1С: ${t.status ?? '—'}${t.line_1c ? ` · ${t.line_1c}` : ''}${t.started_at ? ` · начат ${fmt(t.started_at)}` : ''}`,
    `${fmt(t.start)} — ${fmt(t.end)}`,
    `ГП к продаже: ${fmtDate(t.available_from)}`,
    t.locked ? 'Время и линия зафиксированы вручную' : t.line_locked ? 'Линия закреплена вручную, время — автоматически' : 'Расставлен автоматически',
    ...t.warnings.map((w) => `⚠ ${w}`),
  ]
  return lines.map((l, i) => (i === 0 ? l : esc(l))).join('<br>')
}

export default function GanttPage() {
  const container = useRef<HTMLDivElement>(null)
  const timeline = useRef<Timeline | null>(null)
  const [data, setData] = useState<Schedule | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const range = useMemo(() => {
    const from = new Date(Date.now() - 7 * DAY)
    return { from: isoDate(from), to: isoDate(new Date(from.getTime() + 120 * DAY)) }
  }, [])

  const load = useCallback(async () => {
    try {
      setData(await scheduleApi.schedule(range.from, range.to))
    } catch (e) {
      setError((e as Error).message)
    }
  }, [range])

  useEffect(() => {
    load()
  }, [load])

  const act = async (fn: () => Promise<unknown>, done?: (r: unknown) => string | null) => {
    setBusy(true)
    setError(null)
    try {
      const r = await fn()
      setInfo(done ? done(r) : null)
      await load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  // строки линий, у которых раскрыты этапы (по умолчанию — все)
  const expanded = useRef<Set<string> | null>(null)
  const [showTasks, setShowTasks] = useState(true)
  const longDays = useRef(false)

  // создаём таймлайн один раз
  useEffect(() => {
    if (!container.current || timeline.current) return
    const now = new Date()
    now.setHours(0, 0, 0, 0)
    const options: TimelineOptions = {
      stack: false,
      orientation: 'top',
      locale: 'ru',
      editable: { updateTime: true, updateGroup: false, add: false, remove: false, overrideItems: false },
      snap: (date) => new Date(Math.round(date.valueOf() / 900_000) * 900_000), // шаг 15 минут
      zoomMin: 6 * 3600_000,
      zoomMax: 180 * DAY,
      start: new Date(now.getTime() - DAY),
      end: new Date(now.getTime() + 9 * DAY),
      margin: { item: { horizontal: 0, vertical: 4 }, axis: 2 },
      tooltip: { followMouse: true },
      groupOrder: 'order',
      maxHeight: 720,
      verticalScroll: true,
      showCurrentTime: true,
      format: timeAxisFormat(() => longDays.current) as unknown as TimelineOptions['format'],
      // разметка подписей собирается в ganttModel из экранированных строк — фильтр vis вырезал бы классы
      xss: { disabled: true },
    }
    const tl = new Timeline(container.current, [], [], options)
    // полные названия дней недели — пока на экране не больше 10 дней
    const fitLabels = () => {
      const w = tl.getWindow()
      const long = w.end.getTime() - w.start.getTime() <= 10.5 * DAY && (container.current?.clientWidth ?? 0) > 1000
      if (long !== longDays.current) {
        longDays.current = long
        tl.redraw()
      }
    }
    tl.on('rangechanged', fitLabels)
    fitLabels()
    // клик по строке линии раскрывает/сворачивает её этапы — запоминаем, чтобы пережить перезагрузку данных
    tl.on('click', (props: { what?: string; group?: string | number }) => {
      const g = String(props.group ?? '')
      if (props.what !== 'group-label' || !g.startsWith('line:') || !expanded.current) return
      if (expanded.current.has(g)) expanded.current.delete(g)
      else expanded.current.add(g)
    })
    timeline.current = tl
  }, [])

  // обновляем данные и обработчик перетаскивания
  useEffect(() => {
    const tl = timeline.current
    if (!tl || !data) return
    if (!expanded.current) expanded.current = new Set(data.lines.map((l) => `line:${l.code}`))
    const { items, refs } = buildItems(data, tooltip)
    tl.setGroups(buildGroups(data, expanded.current))
    tl.setItems(items)
    tl.setOptions({
      onMove: (item, callback) => {
        callback(null) // позицию задаст сервер после перепланирования
        const ref = refs.get(String(item.id))
        if (!ref) return
        const { task, segment } = ref
        // сдвиг отрезка = сдвиг всего этапа
        const start = new Date(new Date(task.start!).getTime() + (new Date(item.start).getTime() - segment.start))
        act(
          () => scheduleApi.patchTask(task.id, { line_code: task.line_code ?? undefined, start: localIso(start) }),
          () => `Этап ${task.number} зафиксирован с ${fmt(localIso(start))}; остальные перепланированы`,
        )
      },
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])

  const toggleAll = (show: boolean) => {
    setShowTasks(show)
    if (!data || !timeline.current) return
    expanded.current = new Set(show ? data.lines.map((l) => `line:${l.code}`) : [])
    timeline.current.setGroups(buildGroups(data, expanded.current))
  }

  const zoom = (days: number) => {
    const today = new Date()
    today.setHours(0, 0, 0, 0)
    timeline.current?.setWindow(new Date(today.getTime() - DAY), new Date(today.getTime() + days * DAY))
  }

  const tasks = useMemo(
    () =>
      [...(data?.tasks ?? [])].sort(
        (a, b) => (a.start ?? '9999').localeCompare(b.start ?? '9999') || a.number.localeCompare(b.number),
      ),
    [data],
  )
  const weeks = useMemo(() => [...new Set((data?.load ?? []).map((l) => l.week_start))].sort().slice(0, 12), [data])
  const loadOf = (line: string, week: string) => data?.load.find((l) => l.line_code === line && l.week_start === week)
  const warned = tasks.filter((t) => t.warnings.length).length

  return (
    <Stack>
      <div>
        <Title order={3}>Гант 2 ступени</Title>
        <Text c="dimmed" size="sm">
          Как «График этапов производства» в 1С: строка линии со всеми её этапами (бордовым — переналадка 1 ч), под ней —
          строки этапов; полосы разбиты по рабочим сменам. Клик по названию линии сворачивает её этапы. Этап из своей
          строки можно перетащить по времени — он зафиксируется (📌), остальные перестроятся вокруг. Линию выбирают в
          таблице заказов (📍). Начатые в 1С этапы (▶) стоят на линии из 1С и идут первыми; показан остаток
          «запланировано − выпущено».
        </Text>
      </div>
      <Group>
        <Button loading={busy} onClick={() => act(scheduleApi.sync, (r) => {
          const s = r as { added: number; updated: number; removed: number; total: number }
          return `Заказов: ${s.total} (новых ${s.added}, изменено ${s.updated}, закрыто ${s.removed})`
        })}>
          Загрузить заказы из последнего снимка 1С
        </Button>
        <Button variant="light" loading={busy} onClick={() => act(scheduleApi.replan, () => 'Перепланировано')}>
          Перепланировать
        </Button>
        <Button.Group>
          <Button variant="default" onClick={() => zoom(3)}>3 дня</Button>
          <Button variant="default" onClick={() => zoom(9)}>Неделя</Button>
          <Button variant="default" onClick={() => zoom(14)}>2 недели</Button>
          <Button variant="default" onClick={() => zoom(60)}>2 месяца</Button>
        </Button.Group>
        <Switch
          label="Этапы под линиями"
          checked={showTasks}
          onChange={(e) => toggleAll(e.currentTarget.checked)}
        />
      </Group>
      {error && <Alert color="red">{error}</Alert>}
      {info && <Alert color="teal" withCloseButton onClose={() => setInfo(null)}>{info}</Alert>}
      {data && data.tasks.length === 0 && (
        <Text c="dimmed">Заказов пока нет — загрузите их из последнего снимка 1С.</Text>
      )}

      <Box className="gantt gantt-1c" ref={container} />

      {data && data.tasks.length > 0 && (
        <>
          <Title order={5} mt="sm">
            Загрузка линий по неделям
          </Title>
          <ScrollArea>
            <Table withTableBorder fz="xs">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Линия</Table.Th>
                  {weeks.map((w) => (
                    <Table.Th key={w} ta="center">
                      с {new Date(w).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })}
                    </Table.Th>
                  ))}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {data.lines.map((l) => (
                  <Table.Tr key={l.code}>
                    <Table.Td fw={600}>{l.title ?? l.code}</Table.Td>
                    {weeks.map((w) => {
                      const v = loadOf(l.code, w)
                      const pct = v?.load == null ? null : Math.round(v.load * 100)
                      const bg = pct == null ? '#f1f3f5' : pct >= 100 ? '#ffc9c9' : pct >= 80 ? '#ffe8cc' : pct > 0 ? '#d3f9d8' : undefined
                      return (
                        <Tooltip key={w} label={v ? `${num.format(v.busy_hours)} из ${num.format(v.available_hours)} ч` : ''}>
                          <Table.Td ta="center" bg={bg}>
                            {pct == null ? 'нет смен' : `${pct}%`}
                          </Table.Td>
                        </Tooltip>
                      )
                    })}
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea>

          <Group mt="sm">
            <Title order={5}>Заказы</Title>
            {warned > 0 && <Badge color="orange">с предупреждениями: {warned}</Badge>}
          </Group>
          <Table striped fz="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Заказ</Table.Th>
                <Table.Th>ГП</Table.Th>
                <Table.Th>Статус 1С</Table.Th>
                <Table.Th ta="right">Осталось</Table.Th>
                <Table.Th>Линия в 1С</Table.Th>
                <Table.Th>Линия</Table.Th>
                <Table.Th>Начало</Table.Th>
                <Table.Th>Окончание</Table.Th>
                <Table.Th>ГП к продаже</Table.Th>
                <Table.Th>Время зафиксировано</Table.Th>
                <Table.Th>Предупреждения</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {tasks.map((t) => (
                <Table.Tr key={t.id}>
                  <Table.Td style={{ whiteSpace: 'nowrap' }}>{t.number}</Table.Td>
                  <Table.Td>{t.item}</Table.Td>
                  <Table.Td>
                    {t.status === 'Начат' ? (
                      <Badge size="sm" variant="light" color="green">
                        Начат
                      </Badge>
                    ) : (
                      <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
                        {t.status ?? '—'}
                      </Text>
                    )}
                    {t.started_at && (
                      <Text size="xs" c="dimmed">
                        с {fmt(t.started_at)}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td ta="right">
                    {num.format(t.qty)}
                    {!!t.qty_done && (
                      <Text size="xs" c="dimmed">
                        выпущено {num.format(t.qty_done)} из {num.format(t.qty_plan ?? 0)}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs">{t.line_1c ?? '—'}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Select
                      size="xs"
                      w={150}
                      allowDeselect={false}
                      value={t.line_locked || t.locked ? t.line_code : 'auto'}
                      data={[
                        { value: 'auto', label: `Авто${t.line_code && !t.line_locked && !t.locked ? ` (${t.line_code})` : ''}` },
                        ...(data?.lines ?? []).filter((l) => l.group === t.line_group).map((l) => ({ value: l.code, label: l.code })),
                      ]}
                      onChange={(v) => {
                        if (!v) return
                        act(
                          () =>
                            v === 'auto'
                              ? scheduleApi.patchTask(t.id, { pin_line: false, locked: false })
                              : scheduleApi.patchTask(t.id, { line_code: v, pin_line: true }),
                          () => (v === 'auto' ? `Заказ ${t.number}: линия выбирается автоматически` : `Заказ ${t.number} закреплён за ${v}`),
                        )
                      }}
                    />
                  </Table.Td>
                  <Table.Td>{fmt(t.start)}</Table.Td>
                  <Table.Td>{fmt(t.end)}</Table.Td>
                  <Table.Td>{fmtDate(t.available_from)}</Table.Td>
                  <Table.Td>
                    <Switch
                      size="xs"
                      checked={t.locked}
                      onChange={(e) => act(() => scheduleApi.patchTask(t.id, { locked: e.currentTarget.checked }))}
                    />
                  </Table.Td>
                  <Table.Td>
                    {t.warnings.map((w) => (
                      <Text key={w} size="xs" c="orange.8">
                        {w}
                      </Text>
                    ))}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </>
      )}
    </Stack>
  )
}
