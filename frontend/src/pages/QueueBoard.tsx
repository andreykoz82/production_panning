// Очередь заказов по линиям: перетаскивание карточек меняет порядок на линии
// и переносит заказ на другую линию той же группы. Начатые в 1С этапы стоят первыми и не двигаются.

import { DragDropContext, Draggable, Droppable, type DropResult } from '@hello-pangea/dnd'
import { ActionIcon, Badge, Box, Button, Group, Paper, SimpleGrid, Stack, Text, Tooltip } from '@mantine/core'
import {
  IconAlertTriangle,
  IconArrowDown,
  IconArrowUp,
  IconGripVertical,
  IconLock,
  IconRefresh,
} from '@tabler/icons-react'
import { useEffect, useMemo, useState } from 'react'

import type { Schedule, ScheduleTask } from '../api'
import { Section } from '../ui'

const num = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const hrs = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const dm = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
    : '—'
const monthLabel = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString('ru-RU', { month: 'short', year: '2-digit' }) : null

const isStarted = (t: ScheduleTask) => t.status === 'Начат'
const shortNo = (n: string) => n.replace(/^[^-]*-0*/, '')

type Queues = Record<string, ScheduleTask[]>

function buildQueues(data: Schedule): Queues {
  const q: Queues = Object.fromEntries(data.lines.map((l) => [l.code, []]))
  for (const t of data.tasks) if (t.line_code && q[t.line_code]) q[t.line_code].push(t)
  for (const list of Object.values(q))
    list.sort(
      (a, b) =>
        Number(isStarted(b)) - Number(isStarted(a)) ||
        (a.start ?? '9999').localeCompare(b.start ?? '9999') ||
        a.number.localeCompare(b.number),
    )
  return q
}

export default function QueueBoard({
  data,
  busy,
  onSave,
  onReset,
}: {
  data: Schedule
  busy: boolean
  onSave: (queues: Record<string, number[]>, message: string) => void
  onReset: (line: string) => void
}) {
  const [queues, setQueues] = useState<Queues>(() => buildQueues(data))
  useEffect(() => setQueues(buildQueues(data)), [data])

  const groups = useMemo(() => {
    const out: { group: string; lines: Schedule['lines'] }[] = []
    for (const l of data.lines) {
      const g = out.find((x) => x.group === l.group)
      if (g) g.lines.push(l)
      else out.push({ group: l.group, lines: [l] })
    }
    return out
  }, [data])
  const groupOf = (line: string) => data.lines.find((l) => l.code === line)?.group
  const title = (line: string) => data.lines.find((l) => l.code === line)?.title ?? line

  const save = (next: Queues, lines: string[], message: string) => {
    setQueues(next) // сразу показываем новый порядок, сервер перепланирует
    onSave(Object.fromEntries(lines.map((l) => [l, next[l].filter((t) => !isStarted(t)).map((t) => t.id)])), message)
  }

  const onDragEnd = (r: DropResult) => {
    const { source, destination } = r
    if (!destination) return
    const from = source.droppableId
    const to = destination.droppableId
    if (groupOf(from) !== groupOf(to)) return
    const startedFrom = queues[from].filter(isStarted).length
    const startedTo = queues[to].filter(isStarted).length
    const src = [...queues[from]]
    const [task] = src.splice(source.index + startedFrom, 1)
    const dst = from === to ? src : [...queues[to]]
    // начатые всегда впереди — встать перед ними нельзя
    dst.splice(Math.max(destination.index + startedTo, startedTo), 0, task)
    if (from === to && source.index === destination.index) return
    const next = { ...queues, [from]: src, [to]: dst }
    save(
      next,
      from === to ? [from] : [from, to],
      from === to
        ? `${title(to)}: заказ ${shortNo(task.number)} — ${destination.index + 1}-й в очереди`
        : `Заказ ${shortNo(task.number)} перенесён на ${title(to)}, ${destination.index + 1}-й в очереди`,
    )
  }

  const move = (line: string, idx: number, delta: number) => {
    const list = [...queues[line]]
    const started = list.filter(isStarted).length
    const j = idx + delta
    if (j < started || j >= list.length) return
    ;[list[idx], list[j]] = [list[j], list[idx]]
    save({ ...queues, [line]: list }, [line], `${title(line)}: очередь изменена`)
  }

  return (
    <DragDropContext onDragEnd={onDragEnd}>
      <Stack gap="lg">
        {groups.map(({ group, lines }) => (
          <Section
            key={group}
            title={group}
            description="Перетащите карточку, чтобы поменять порядок или перенести заказ на другую линию группы"
          >
            <SimpleGrid cols={{ base: 1, md: Math.min(lines.length, 3) }} spacing="md">
              {lines.map((l) => {
                const list = queues[l.code] ?? []
                const started = list.filter(isStarted)
                const rest = list.filter((t) => !isStarted(t))
                const manual = rest.some((t) => t.line_source !== '1c')
                const last = list.reduce<string | null>((m, t) => (t.end && (!m || t.end > m) ? t.end : m), null)
                const hours = list.reduce((s, t) => s + t.hours, 0)
                return (
                  <Paper key={l.code} withBorder radius="md" p="sm" bg="gray.0">
                    <Group justify="space-between" mb="xs" wrap="nowrap">
                      <Box>
                        <Text fw={650}>{l.title ?? l.code}</Text>
                        <Text size="xs" c="dimmed">
                          {list.length ? `${list.length} зак. · ${hrs.format(hours)} ч · до ${dm(last)}` : 'свободна'}
                        </Text>
                      </Box>
                      {manual && (
                        <Tooltip label="Вернуть заказы линии на линии из 1С, порядок — по приоритету">
                          <Button
                            size="compact-xs"
                            variant="subtle"
                            color="gray"
                            leftSection={<IconRefresh size={12} />}
                            disabled={busy}
                            onClick={() => onReset(l.code)}
                          >
                            Как в 1С
                          </Button>
                        </Tooltip>
                      )}
                    </Group>

                    <Stack gap={6}>
                      {started.map((t) => (
                        <TaskCard key={t.id} t={t} locked />
                      ))}
                      <Droppable droppableId={l.code}>
                        {(drop, snap) => (
                          <Stack
                            gap={6}
                            ref={drop.innerRef}
                            {...drop.droppableProps}
                            mih={48}
                            p={snap.isDraggingOver ? 4 : 0}
                            style={{
                              borderRadius: 8,
                              background: snap.isDraggingOver ? 'var(--mantine-color-brand-0)' : undefined,
                              transition: 'background 120ms',
                            }}
                          >
                            {rest.map((t, i) => (
                              <Draggable key={t.id} draggableId={String(t.id)} index={i} isDragDisabled={busy}>
                                {(drag, ds) => (
                                  <div ref={drag.innerRef} {...drag.draggableProps}>
                                    <TaskCard
                                      t={t}
                                      dragging={ds.isDragging}
                                      handle={drag.dragHandleProps}
                                      onUp={i > 0 ? () => move(l.code, i + started.length, -1) : undefined}
                                      onDown={
                                        i < rest.length - 1 ? () => move(l.code, i + started.length, 1) : undefined
                                      }
                                    />
                                  </div>
                                )}
                              </Draggable>
                            ))}
                            {drop.placeholder}
                            {rest.length === 0 && !snap.isDraggingOver && (
                              <Text size="xs" c="dimmed" ta="center" py="xs">
                                перетащите сюда заказ
                              </Text>
                            )}
                          </Stack>
                        )}
                      </Droppable>
                    </Stack>
                  </Paper>
                )
              })}
            </SimpleGrid>
          </Section>
        ))}
      </Stack>
    </DragDropContext>
  )
}

function TaskCard({
  t,
  locked,
  dragging,
  handle,
  onUp,
  onDown,
}: {
  t: ScheduleTask
  locked?: boolean
  dragging?: boolean
  handle?: object | null
  onUp?: () => void
  onDown?: () => void
}) {
  const stockout = monthLabel(t.stockout_month)
  return (
    <Paper
      withBorder
      radius="md"
      p={8}
      shadow={dragging ? 'md' : 'xs'}
      bg={locked ? 'green.0' : t.warnings.length ? 'orange.0' : t.stm ? 'violet.0' : 'white'}
      style={{
        borderColor: locked ? 'var(--mantine-color-green-4)' : t.stm ? 'var(--mantine-color-violet-3)' : undefined,
      }}
    >
      <Group gap={6} wrap="nowrap" align="flex-start">
        {locked ? (
          <Tooltip label="Начат в 1С — первый на линии, место не меняется">
            <Box pt={2} c="green.7">
              <IconLock size={16} />
            </Box>
          </Tooltip>
        ) : (
          <Box {...(handle ?? {})} pt={2} c="gray.5" style={{ cursor: 'grab' }}>
            <IconGripVertical size={16} />
          </Box>
        )}
        <Box style={{ flex: 1, minWidth: 0 }}>
          <Group gap={6} wrap="nowrap" justify="space-between">
            <Text size="xs" fw={700} c="dimmed">
              {shortNo(t.number)}
            </Text>
            <Group gap={4} wrap="nowrap">
              {t.stm && (
                <Tooltip label="СТМ — заказ поставлен по письму клиента">
                  <Badge size="xs" color="violet" variant="filled">
                    СТМ
                  </Badge>
                </Tooltip>
              )}
              {locked && (
                <Badge size="xs" color="green">
                  начат
                </Badge>
              )}
              {stockout && !locked && !t.stm && (
                <Tooltip label="Когда кончится запас ГП — по нему приоритет">
                  <Badge size="xs" color="gray">
                    запас до {stockout}
                  </Badge>
                </Tooltip>
              )}
              {t.warnings.length > 0 && (
                <Tooltip label={t.warnings.join('\n')} multiline w={320}>
                  <Box c="orange.7" lh={0}>
                    <IconAlertTriangle size={15} />
                  </Box>
                </Tooltip>
              )}
            </Group>
          </Group>
          <Text size="sm" fw={500} lineClamp={2} lh={1.25}>
            {t.item}
          </Text>
          <Group gap={8} mt={2} justify="space-between" wrap="nowrap">
            <Text size="xs" c="dimmed">
              {num.format(t.qty)} шт · {hrs.format(t.hours)} ч
              {t.qty_done ? ` · выпущено ${num.format(t.qty_done)}` : ''}
            </Text>
            {!locked && (onUp || onDown) && (
              <Group gap={0} wrap="nowrap">
                <ActionIcon size="xs" variant="subtle" color="gray" disabled={!onUp} onClick={onUp} aria-label="Выше">
                  <IconArrowUp size={12} />
                </ActionIcon>
                <ActionIcon
                  size="xs"
                  variant="subtle"
                  color="gray"
                  disabled={!onDown}
                  onClick={onDown}
                  aria-label="Ниже"
                >
                  <IconArrowDown size={12} />
                </ActionIcon>
              </Group>
            )}
          </Group>
          <Text size="xs" c="dimmed">
            {dm(t.start)} → {dm(t.end)}
          </Text>
        </Box>
      </Group>
    </Paper>
  )
}
