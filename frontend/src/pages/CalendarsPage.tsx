import {
  Alert,
  Badge,
  Box,
  Button,
  Group,
  NumberInput,
  SegmentedControl,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core'
import { IconCalendarTime, IconRestore } from '@tabler/icons-react'
import { useCallback, useEffect, useState } from 'react'

import { scheduleApi, type CalendarLine, type CalendarMonth, type Capacity } from '../api'
import { PageHeader, Section } from '../ui'

const num = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const monthName = (iso: string) => new Date(iso).toLocaleDateString('ru-RU', { month: 'long', year: 'numeric' })

const WEEKDAY = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб']
const SHIFT_BG = ['transparent', '#c3fae8', '#63e6be', '#20c997']

function thisMonth() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

export default function CalendarsPage() {
  const [month, setMonth] = useState(thisMonth())
  const [stage, setStage] = useState<'2' | '1' | 'all'>('2')
  const [data, setData] = useState<CalendarMonth | null>(null)
  const [capacity, setCapacity] = useState<Capacity | null>(null)
  const [months, setMonths] = useState('3')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    scheduleApi
      .month(month)
      .then(setData)
      .catch((e: Error) => setError(e.message))
    scheduleApi
      .capacity(month, Number(months))
      .then(setCapacity)
      .catch((e: Error) => setError(e.message))
  }, [month, months])

  useEffect(load, [load])

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
      load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  // клик — следующая сменность 0→1→2→3→0; Shift+клик — вернуть день к шаблону
  const onCell = (line: CalendarLine, idx: number, reset: boolean) => {
    const d = line.days[idx]
    const shifts = reset ? null : (d.shifts + 1) % 4
    act(() => scheduleApi.setDays([{ line_code: line.line_code, day: d.day, shifts }]))
  }

  const lines = (data?.lines ?? []).filter((l) => stage === 'all' || String(l.stage) === stage)

  return (
    <Stack>
      <PageHeader
        title="Календари линий"
        icon={<IconCalendarTime size={24} />}
        description="Шаблон линии — «5/2» (смены в рабочие дни производственного календаря РФ) или «24/7». Любой день можно поменять вручную: клик по клетке — следующая сменность (0 → 1 → 2 → 3), Shift+клик — вернуть к шаблону. После изменения график перепланируется."
      />
      <Group align="flex-end">
        <TextInput
          label="Месяц"
          type="month"
          value={month}
          onChange={(e) => e.currentTarget.value && setMonth(e.currentTarget.value)}
          w={180}
        />
        <SegmentedControl
          value={stage}
          onChange={(v) => setStage(v as '2' | '1' | 'all')}
          data={[
            { value: '2', label: '2 ступень' },
            { value: '1', label: '1 ступень' },
            { value: 'all', label: 'Все линии' },
          ]}
        />
        <Button
          variant="default"
          leftSection={<IconRestore size={16} />}
          loading={busy}
          onClick={() => act(() => scheduleApi.resetMonth(month))}
        >
          Сбросить ручные правки месяца
        </Button>
      </Group>
      {error && <Alert color="red">{error}</Alert>}

      {capacity && (
        <Section
          title="Сколько выпустят группы линий при таком графике"
          description={`Часы работы по календарю × норма линии. Текущий месяц — с ${new Date(capacity.from).toLocaleDateString('ru-RU')}.${
            capacity.horizon_months
              ? ` Предстоит выпустить = остаток открытых этапов + потребность к фасовке из последнего расчёта на ${capacity.horizon_months} мес. — сравнивайте с мощностью за тот же срок.`
              : ''
          }`}
          actions={
            <SegmentedControl
              size="xs"
              value={months}
              onChange={setMonths}
              data={[
                { value: '1', label: '1 мес.' },
                { value: '3', label: '3 мес.' },
                { value: '6', label: '6 мес.' },
              ]}
            />
          }
        >
          <Box style={{ overflowX: 'auto' }}>
            <Table fz="sm">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Группа линий</Table.Th>
                  {capacity.months.map((m) => (
                    <Table.Th key={m} ta="right" style={{ textTransform: 'capitalize' }}>
                      {monthName(m)}
                    </Table.Th>
                  ))}
                  <Table.Th ta="right">Итого</Table.Th>
                  <Table.Th ta="right">Предстоит выпустить</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {capacity.groups
                  .filter((g) => stage === 'all' || String(g.stage) === stage)
                  .map((g) => {
                    const demand = g.need != null || g.open_orders ? (g.need ?? 0) + (g.open_orders ?? 0) : null
                    const load = demand != null && g.total ? demand / g.total : null
                    return (
                      <Table.Tr key={g.group}>
                        <Table.Td>
                          <Text size="sm" fw={600}>
                            {g.group}
                          </Text>
                          <Text size="xs" c="dimmed">
                            {g.lines.join(', ')}
                          </Text>
                        </Table.Td>
                        {g.months.map((m) => (
                          <Table.Td key={m.month} ta="right">
                            <Text size="sm" fw={500}>
                              {num.format(m.output)} {g.unit}
                            </Text>
                            <Text size="xs" c="dimmed">
                              {num.format(m.hours)} ч
                            </Text>
                          </Table.Td>
                        ))}
                        <Table.Td ta="right">
                          <Text size="sm" fw={700}>
                            {num.format(g.total)} {g.unit}
                          </Text>
                          <Text size="xs" c="dimmed">
                            {num.format(g.total_hours)} ч
                          </Text>
                        </Table.Td>
                        <Table.Td ta="right">
                          {demand != null ? (
                            <>
                              <Text size="sm">
                                {num.format(demand)} {g.unit}
                              </Text>
                              <Text size="xs" c="dimmed">
                                этапы {num.format(g.open_orders ?? 0)} + к фасовке {num.format(g.need ?? 0)}
                              </Text>
                              {load != null && (
                                <Badge size="sm" mt={2} color={load <= 0.8 ? 'brand' : load <= 1 ? 'yellow' : 'red'}>
                                  загрузка {Math.round(load * 100)}%
                                </Badge>
                              )}
                            </>
                          ) : (
                            <Text size="xs" c="dimmed">
                              —
                            </Text>
                          )}
                        </Table.Td>
                      </Table.Tr>
                    )
                  })}
              </Table.Tbody>
            </Table>
          </Box>
        </Section>
      )}

      {data && (
        <Section p={0}>
          <Box style={{ overflowX: 'auto' }}>
            <Table withColumnBorders highlightOnHover={false} fz="xs" style={{ minWidth: 1100 }}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th miw={150}>Линия</Table.Th>
                  <Table.Th miw={170}>Шаблон</Table.Th>
                  {data.days.map((d) => {
                    const dt = new Date(d.day)
                    return (
                      <Table.Th key={d.day} ta="center" p={2} bg={d.workday ? undefined : 'gray.1'}>
                        <div>{dt.getDate()}</div>
                        <Text size="10px" c="dimmed">
                          {WEEKDAY[dt.getDay()]}
                        </Text>
                      </Table.Th>
                    )
                  })}
                  <Table.Th ta="right">Часов</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {lines.map((line) => (
                  <Table.Tr key={line.line_code}>
                    <Table.Td>
                      <Text size="sm" fw={600}>
                        {line.title ?? line.line_code}
                      </Text>
                      <Text size="10px" c="dimmed">
                        {line.group}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Group gap={4} wrap="nowrap">
                        <Select
                          size="xs"
                          w={80}
                          data={['5/2', '24/7']}
                          value={line.mode}
                          allowDeselect={false}
                          onChange={(v) =>
                            v && act(() => scheduleApi.setTemplate(line.line_code, v, line.template_shifts))
                          }
                        />
                        <NumberInput
                          size="xs"
                          w={64}
                          min={0}
                          max={3}
                          value={line.template_shifts}
                          suffix=" см."
                          onChange={(v) => {
                            const n = Number(v)
                            if (n >= 0 && n <= 3 && n !== line.template_shifts)
                              act(() => scheduleApi.setTemplate(line.line_code, line.mode, n))
                          }}
                        />
                      </Group>
                    </Table.Td>
                    {line.days.map((d, idx) => (
                      <Tooltip
                        key={d.day}
                        label={`${new Date(d.day).toLocaleDateString('ru-RU')}: ${d.shifts} см.${d.manual ? ` (вручную, по шаблону ${d.template})` : ''}${d.reason ? ` — ${d.reason}` : ''}`}
                        openDelay={400}
                      >
                        <Table.Td
                          p={0}
                          ta="center"
                          style={{
                            cursor: 'pointer',
                            background: SHIFT_BG[d.shifts],
                            outline: d.manual ? '2px solid #fd7e14' : undefined,
                            outlineOffset: -2,
                            minWidth: 26,
                            height: 30,
                          }}
                          onClick={(e) => onCell(line, idx, e.shiftKey)}
                        >
                          {d.shifts || ''}
                        </Table.Td>
                      </Tooltip>
                    ))}
                    <Table.Td ta="right">{line.hours}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Box>
        </Section>
      )}
      <Text size="xs" c="dimmed">
        Оранжевая рамка — день изменён вручную. Серый столбец — выходной или праздник по производственному календарю.
      </Text>
    </Stack>
  )
}
