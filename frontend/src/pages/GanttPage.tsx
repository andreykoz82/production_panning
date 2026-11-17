import 'vis-timeline/styles/vis-timeline-graph2d.min.css'
import './gantt.css'

import { Alert, Badge, Box, Button, Group, ScrollArea, Select, Stack, Switch, Table, Text, Title, Tooltip } from '@mantine/core'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Timeline, type TimelineGroup, type TimelineItem, type TimelineOptions } from 'vis-timeline/standalone'

import { scheduleApi, type Schedule, type ScheduleTask } from '../api'

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
    `<b>${t.number}</b> · ${t.item}`,
    `${num.format(t.qty)} шт · ${t.hours} ч${t.changeover ? ' (с переналадкой 1 ч)' : ''}`,
    `${fmt(t.start)} — ${fmt(t.end)}`,
    `ГП к продаже: ${fmtDate(t.available_from)}`,
    t.locked ? 'Время и линия зафиксированы вручную' : t.line_locked ? 'Линия закреплена вручную, время — автоматически' : 'Расставлен автоматически',
    ...t.warnings.map((w) => `⚠ ${w}`),
  ]
  return lines.join('<br>')
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

  // создаём таймлайн один раз
  useEffect(() => {
    if (!container.current || timeline.current) return
    const options: TimelineOptions = {
      stack: false,
      orientation: 'top',
      locale: 'ru',
      editable: { updateTime: true, updateGroup: true, add: false, remove: false, overrideItems: false },
      snap: (date) => new Date(Math.round(date.valueOf() / 900_000) * 900_000), // шаг 15 минут
      zoomMin: 6 * 3600_000,
      zoomMax: 180 * DAY,
      start: new Date(Date.now() - DAY),
      end: new Date(Date.now() + 21 * DAY),
      margin: { item: 6 },
      tooltip: { followMouse: true },
      groupOrder: 'order',
    }
    timeline.current = new Timeline(container.current, [], [], options)
  }, [])

  // обновляем данные и обработчик перетаскивания
  useEffect(() => {
    const tl = timeline.current
    if (!tl || !data) return
    const groups: TimelineGroup[] = data.lines.map((l, i) => ({
      id: l.code,
      order: i,
      content: `<div class="group-name">${l.code}</div><div class="group-sub">${l.group.replace('Линия ', '')}</div>`,
    }))
    const items: TimelineItem[] = [
      ...data.off.map((o, i) => ({
        id: `off-${i}`,
        group: o.line_code,
        start: new Date(o.start),
        end: new Date(o.end),
        type: 'background' as const,
        className: 'off',
        content: '',
      })),
      ...data.tasks
        .filter((t) => t.line_code && t.start && t.end)
        .map((t) => ({
          id: t.id,
          group: t.line_code!,
          start: new Date(t.start!),
          end: new Date(t.end!),
          content: `${t.locked ? '📌 ' : t.line_locked ? '📍 ' : ''}${t.item} · ${num.format(t.qty)}`,
          title: tooltip(t),
          className: ['task', t.warnings.length ? 'warn' : '', t.locked ? 'locked' : ''].join(' '),
        })),
    ]
    tl.setGroups(groups)
    tl.setItems(items)
    tl.setOptions({
      onMove: (item, callback) => {
        callback(null) // позицию задаст сервер после перепланирования
        const task = data.tasks.find((t) => t.id === item.id)
        if (!task) return
        act(
          () => scheduleApi.patchTask(task.id, { line_code: String(item.group), start: localIso(new Date(item.start)) }),
          () => `Заказ ${task.number} зафиксирован; остальные перепланированы`,
        )
      },
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])

  const zoom = (days: number) => {
    const now = Date.now()
    timeline.current?.setWindow(new Date(now - DAY / 2), new Date(now + days * DAY))
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
          Открытые заказы из 1С расставляются по линиям своей группы с учётом календаря, переналадки 1 ч и приоритета из
          последнего расчёта потребности. Перетащите заказ — он зафиксируется (📌), остальные перестроятся вокруг.
          Линию можно выбрать в таблице заказов (📍): линия закрепится, а время подберётся автоматически.
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
          <Button variant="default" onClick={() => zoom(14)}>2 недели</Button>
          <Button variant="default" onClick={() => zoom(60)}>2 месяца</Button>
        </Button.Group>
      </Group>
      {error && <Alert color="red">{error}</Alert>}
      {info && <Alert color="teal" withCloseButton onClose={() => setInfo(null)}>{info}</Alert>}
      {data && data.tasks.length === 0 && (
        <Text c="dimmed">Заказов пока нет — загрузите их из последнего снимка 1С.</Text>
      )}

      <Box className="gantt" ref={container} style={{ border: '1px solid #dee2e6', borderRadius: 8 }} />

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
                    <Table.Td fw={600}>{l.code}</Table.Td>
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
                <Table.Th ta="right">Кол-во</Table.Th>
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
                  <Table.Td ta="right">{num.format(t.qty)}</Table.Td>
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
