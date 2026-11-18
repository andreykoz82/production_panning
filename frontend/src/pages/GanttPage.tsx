import 'vis-timeline/styles/vis-timeline-graph2d.min.css'
import './gantt.css'

import {
  Alert,
  Badge,
  Box,
  Button,
  Group,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Tabs,
  Text,
} from '@mantine/core'
import {
  IconAlertTriangle,
  IconCloudDownload,
  IconLayoutKanban,
  IconListDetails,
  IconPlayerPlay,
  IconRefresh,
  IconTimeline,
  IconTruckDelivery,
} from '@tabler/icons-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Timeline, type TimelineOptions } from 'vis-timeline/standalone'

import { scheduleApi, type Schedule, type ScheduleTask } from '../api'
import { PageHeader, Section, StatCard } from '../ui'
import { buildGroups, buildItems, esc, timeAxisFormat } from './ganttModel'
import QueueBoard from './QueueBoard'

const DAY = 86_400_000
const num = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const isoDate = (d: Date) => d.toISOString().slice(0, 10)
const fmt = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
    : '—'
const fmtDate = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString('ru-RU') : '—')
const fmtMonth = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString('ru-RU', { month: 'short', year: 'numeric' }) : '—'
const STARTED = 'Начат'

function tooltip(t: ScheduleTask) {
  const lines = [
    `<b>${esc(t.number)}</b> · ${esc(t.item)}`,
    `${num.format(t.qty)} шт · ${t.hours} ч${t.changeover ? ' (с переналадкой 1 ч)' : ''}`,
    ...(t.qty_done ? [`Выпущено ${num.format(t.qty_done)} из ${num.format(t.qty_plan ?? 0)}`] : []),
    `1С: ${t.status ?? '—'}${t.line_1c ? ` · ${t.line_1c}` : ''}${t.started_at ? ` · начат ${fmt(t.started_at)}` : ''}`,
    `${fmt(t.start)} — ${fmt(t.end)}`,
    `ГП к продаже: ${fmtDate(t.available_from)}`,
    t.status === STARTED
      ? 'Начат в 1С — первый на линии, место зафиксировано'
      : t.line_locked
        ? 'Очередь задана вручную; перетащите, чтобы поменять место'
        : 'Расставлен автоматически; перетащите, чтобы поменять место в очереди',
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
      maxHeight: Math.max(420, window.innerHeight - 330),
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
      // перетаскивание этапа по времени = новое место в очереди его линии
      onMove: (item, callback) => {
        callback(null) // точное время задаст сервер после перепланирования
        const ref = refs.get(String(item.id))
        if (!ref || !ref.task.line_code) return
        const { task, segment } = ref
        const dropAt = new Date(task.start!).getTime() + (new Date(item.start).getTime() - segment.start)
        const queue = data.tasks
          .filter((t) => t.line_code === task.line_code && t.status !== STARTED && t.id !== task.id && t.start)
          .sort((a, b) => a.start!.localeCompare(b.start!))
        let pos = queue.findIndex((t) => new Date(t.start!).getTime() > dropAt)
        if (pos < 0) pos = queue.length
        const ids = queue.map((t) => t.id)
        ids.splice(pos, 0, task.id)
        act(
          () => scheduleApi.setQueues({ [task.line_code!]: ids }),
          () => `Заказ ${task.number} — ${pos + 1}-й в очереди после начатых; остальные перепланированы`,
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
  const warned = tasks.filter((t) => t.warnings.length).length
  const startedCount = tasks.filter((t) => t.status === STARTED).length
  const [tab, setTab] = useState<string | null>('chart')
  const [filter, setFilter] = useState<'all' | 'warn' | 'started'>('all')
  const shown = tasks.filter(
    (t) => filter === 'all' || (filter === 'warn' ? t.warnings.length > 0 : t.status === STARTED),
  )

  // vis-timeline не видит своих размеров, пока вкладка скрыта
  useEffect(() => {
    if (tab === 'chart') setTimeout(() => timeline.current?.redraw(), 0)
  }, [tab])

  return (
    <Stack gap="md">
      <PageHeader
        title="График производства · 2 ступень"
        icon={<IconTimeline size={24} />}
        description="Как «График этапов производства» в 1С. Начатые этапы стоят первыми на своей линии и не двигаются; на графике — остаток «запланировано − выпущено». Порядок меняется перетаскиванием этапа на диаграмме или карточки во вкладке «Очередь»."
        actions={
          <>
            <Button
              leftSection={<IconCloudDownload size={16} />}
              loading={busy}
              onClick={() =>
                act(scheduleApi.sync, (r) => {
                  const s = r as { added: number; updated: number; removed: number; total: number }
                  return `Заказов: ${s.total} (новых ${s.added}, изменено ${s.updated}, закрыто ${s.removed})`
                })
              }
            >
              Загрузить заказы из 1С
            </Button>
            <Button
              variant="default"
              leftSection={<IconRefresh size={16} />}
              loading={busy}
              onClick={() => act(scheduleApi.replan, () => 'Перепланировано')}
            >
              Перепланировать
            </Button>
          </>
        }
      />

      {data && data.tasks.length > 0 && (
        <SimpleGrid cols={{ base: 2, md: 4 }}>
          <StatCard icon={<IconTruckDelivery size={20} />} label="Этапов в графике" value={tasks.length} />
          <StatCard icon={<IconPlayerPlay size={20} />} color="green" label="Начато в 1С" value={startedCount} />
          <StatCard
            icon={<IconAlertTriangle size={20} />}
            color={warned ? 'orange' : 'brand'}
            label="С предупреждениями"
            value={warned}
          />
          <StatCard
            icon={<IconTimeline size={20} />}
            color="blue"
            label="Последний этап закончится"
            value={fmtDate(tasks.reduce<string | null>((m, t) => (t.end && (!m || t.end > m) ? t.end : m), null))}
          />
        </SimpleGrid>
      )}

      {error && (
        <Alert color="red" withCloseButton onClose={() => setError(null)}>
          {error}
        </Alert>
      )}
      {info && (
        <Alert color="brand" withCloseButton onClose={() => setInfo(null)}>
          {info}
        </Alert>
      )}
      {data && data.tasks.length === 0 && (
        <Text c="dimmed">Заказов пока нет — загрузите их из последнего снимка 1С.</Text>
      )}

      <Tabs value={tab} onChange={setTab} keepMounted>
        <Tabs.List mb="md">
          <Tabs.Tab value="chart" leftSection={<IconTimeline size={16} />}>
            Диаграмма Ганта
          </Tabs.Tab>
          <Tabs.Tab value="queue" leftSection={<IconLayoutKanban size={16} />}>
            Очередь по линиям
          </Tabs.Tab>
          <Tabs.Tab value="orders" leftSection={<IconListDetails size={16} />}>
            Заказы ({tasks.length})
          </Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="chart">
          <Group mb="sm" justify="space-between">
            <Button.Group>
              <Button variant="default" size="xs" onClick={() => zoom(3)}>
                3 дня
              </Button>
              <Button variant="default" size="xs" onClick={() => zoom(9)}>
                Неделя
              </Button>
              <Button variant="default" size="xs" onClick={() => zoom(14)}>
                2 недели
              </Button>
              <Button variant="default" size="xs" onClick={() => zoom(60)}>
                2 месяца
              </Button>
            </Button.Group>
            <Group gap="lg">
              <Text size="xs" c="dimmed">
                ▶ начат в 1С · 📍 очередь задана вручную · бордовым — переналадка
              </Text>
              <Switch
                label="Этапы под линиями"
                checked={showTasks}
                onChange={(e) => toggleAll(e.currentTarget.checked)}
              />
            </Group>
          </Group>
          <Box className="gantt gantt-1c" ref={container} />
        </Tabs.Panel>

        <Tabs.Panel value="queue">
          {data && (
            <QueueBoard
              data={data}
              busy={busy}
              onSave={(queues, message) =>
                act(
                  () => scheduleApi.setQueues(queues),
                  () => message,
                )
              }
              onReset={(line) =>
                act(
                  () => scheduleApi.resetQueue(line),
                  () => 'Линия вернулась на автоматическую расстановку',
                )
              }
            />
          )}
        </Tabs.Panel>

        <Tabs.Panel value="orders">
          <Group mb="sm">
            <SegmentedControl
              value={filter}
              onChange={(v) => setFilter(v as typeof filter)}
              data={[
                { value: 'all', label: `Все (${tasks.length})` },
                { value: 'started', label: `Начатые (${startedCount})` },
                { value: 'warn', label: `С предупреждениями (${warned})` },
              ]}
            />
          </Group>
          <Section p={0}>
            <Table fz="sm" stickyHeader>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Этап</Table.Th>
                  <Table.Th>ГП</Table.Th>
                  <Table.Th>Статус 1С</Table.Th>
                  <Table.Th ta="right">Осталось</Table.Th>
                  <Table.Th>Запас ГП до</Table.Th>
                  <Table.Th>Линия</Table.Th>
                  <Table.Th>Начало</Table.Th>
                  <Table.Th>Окончание</Table.Th>
                  <Table.Th>ГП к продаже</Table.Th>
                  <Table.Th>Предупреждения</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {shown.map((t) => (
                  <OrderRow key={t.id} t={t} data={data!} act={act} />
                ))}
              </Table.Tbody>
            </Table>
          </Section>
        </Tabs.Panel>
      </Tabs>
    </Stack>
  )
}

function OrderRow({
  t,
  data,
  act,
}: {
  t: ScheduleTask
  data: Schedule
  act: (fn: () => Promise<unknown>, done?: (r: unknown) => string | null) => void
}) {
  const started = t.status === STARTED
  return (
    <Table.Tr bg={t.warnings.length ? 'orange.0' : undefined}>
      <Table.Td style={{ whiteSpace: 'nowrap' }}>
        <Text size="sm" fw={500}>
          {t.number}
        </Text>
        {t.seq != null && (
          <Text size="xs" c="dimmed">
            в очереди №{t.seq + 1}
          </Text>
        )}
      </Table.Td>
      <Table.Td>{t.item}</Table.Td>
      <Table.Td>
        {started ? (
          <Badge size="sm" color="green">
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
      <Table.Td style={{ whiteSpace: 'nowrap' }}>{fmtMonth(t.stockout_month)}</Table.Td>
      <Table.Td>
        <Select
          size="xs"
          w={170}
          allowDeselect={false}
          disabled={started}
          value={t.line_locked ? t.line_code : 'auto'}
          data={[
            {
              value: 'auto',
              label: `Авто${t.line_code && !t.line_locked ? ` (${data.lines.find((l) => l.code === t.line_code)?.title ?? t.line_code})` : ''}`,
            },
            ...data.lines
              .filter((l) => l.group === t.line_group)
              .map((l) => ({ value: l.code, label: l.title ?? l.code })),
          ]}
          onChange={(v) => {
            if (!v) return
            act(
              () =>
                v === 'auto'
                  ? scheduleApi.patchTask(t.id, { pin_line: false })
                  : scheduleApi.patchTask(t.id, { line_code: v, pin_line: true }),
              () =>
                v === 'auto'
                  ? `Заказ ${t.number}: линия выбирается автоматически`
                  : `Заказ ${t.number} — в конец очереди ${v}`,
            )
          }}
        />
        <Text size="xs" c="dimmed" mt={2}>
          в 1С: {t.line_1c ?? '—'}
        </Text>
      </Table.Td>
      <Table.Td style={{ whiteSpace: 'nowrap' }}>{fmt(t.start)}</Table.Td>
      <Table.Td style={{ whiteSpace: 'nowrap' }}>{fmt(t.end)}</Table.Td>
      <Table.Td>{fmtDate(t.available_from)}</Table.Td>
      <Table.Td>
        {t.warnings.map((w) => (
          <Text key={w} size="xs" c="orange.8">
            {w}
          </Text>
        ))}
      </Table.Td>
    </Table.Tr>
  )
}
