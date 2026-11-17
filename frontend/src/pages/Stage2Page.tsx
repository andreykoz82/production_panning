import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  NumberInput,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Tabs,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { planningApi, type PlanRun, type PlanRunDetail, type Stage2Status } from '../api'

const num = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const kg = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const today = () => new Date().toISOString().slice(0, 10)
const month = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString('ru-RU', { month: 'short', year: 'numeric' }) : 'не кончится'
const dmy = (iso: string) => new Date(iso).toLocaleDateString('ru-RU')

const STATUS_COLOR: Record<Stage2Status, string> = {
  'Можно фасовать': 'teal',
  Частично: 'yellow',
  Нельзя: 'red',
  'Нет данных': 'gray',
  'Не требуется': 'gray',
}

function Stat({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <Card withBorder padding="md">
      <Text size="sm" c="dimmed">
        {label}
      </Text>
      <Text size="xl" fw={700}>
        {value}
      </Text>
      {hint && (
        <Text size="xs" c="dimmed">
          {hint}
        </Text>
      )}
    </Card>
  )
}

export default function Stage2Page() {
  const [horizon, setHorizon] = useState<number>(3)
  const [calcDate, setCalcDate] = useState(today())
  const [runs, setRuns] = useState<PlanRun[]>([])
  const [run, setRun] = useState<PlanRunDetail | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [scope, setScope] = useState<'need' | 'all'>('need')
  const [search, setSearch] = useState('')

  const loadRuns = useCallback(async (select?: number) => {
    const list = await planningApi.runs()
    setRuns(list)
    const id = select ?? list[0]?.id
    if (id) setRun(await planningApi.run(id))
  }, [])

  useEffect(() => {
    loadRuns().catch((e: Error) => setError(e.message))
  }, [loadRuns])

  const calculate = async () => {
    setBusy(true)
    setError(null)
    try {
      const r = await planningApi.calculate(horizon, calcDate)
      await loadRuns(r.id)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const lines = useMemo(() => {
    if (!run) return []
    const q = search.trim().toLowerCase()
    return run.lines.filter(
      (l) => (scope === 'all' || l.need > 0) && (!q || `${l.item} ${l.nfp ?? ''}`.toLowerCase().includes(q)),
    )
  }, [run, scope, search])

  const s = run?.summary

  return (
    <Stack>
      <div>
        <Title order={3}>Потребность 2 ступени</Title>
        <Text c="dimmed" size="sm">
          Сколько фасовать, чтобы обеспечить план продаж на N месяцев: план − запас ГП (склад ГП + опт) − открытые
          заказы, не меньше выпуска линии за 1 ч. Из текущего месяца — оставшиеся рабочие дни.
        </Text>
      </div>

      <Group align="flex-end">
        <NumberInput
          label="Горизонт, мес."
          min={1}
          max={24}
          w={140}
          value={horizon}
          onChange={(v) => setHorizon(Number(v) || 1)}
        />
        <TextInput label="Дата расчёта" type="date" w={170} value={calcDate} onChange={(e) => setCalcDate(e.currentTarget.value)} />
        <Button loading={busy} onClick={calculate}>
          Рассчитать
        </Button>
        {runs.length > 0 && (
          <Select
            label="Расчёт"
            w={330}
            value={run?.id.toString() ?? null}
            onChange={(v) => v && planningApi.run(Number(v)).then(setRun)}
            data={runs.map((r) => ({
              value: r.id.toString(),
              label: `#${r.id}: на ${r.params.horizon_months} мес. от ${dmy(r.params.calc_date)} (снимок #${r.snapshot_id})`,
            }))}
          />
        )}
        {run && (
          <Button component="a" href={planningApi.exportUrl(run.id)} variant="light">
            Скачать Excel для диспетчера
          </Button>
        )}
      </Group>

      {error && (
        <Alert color="red" title="Не удалось рассчитать">
          {error}
        </Alert>
      )}
      {!run && !error && <Text c="dimmed">Расчётов ещё нет — задайте горизонт и нажмите «Рассчитать».</Text>}

      {run && s && (
        <>
          <SimpleGrid cols={{ base: 2, md: 4 }}>
            <Stat
              label="Позиций к фасовке"
              value={`${s.items_needed} из ${s.items}`}
              hint={`полностью ${s.items_full}, частично ${s.items_partial}, нельзя ${s.items_blocked}`}
            />
            <Stat
              label="Потребность, шт"
              value={num.format(s.need_units)}
              hint={`можно выпустить сейчас ${num.format(s.feasible_units)}`}
            />
            <Stat label="Материалов в дефиците" value={s.materials_short} />
            <Stat label="Выпустить НФП на 1 ступени" value={`${kg.format(s.nfp_shortage_kg)} кг`} hint="с учётом карантина" />
          </SimpleGrid>
          <Text size="xs" c="dimmed">
            Доля плана в горизонте:{' '}
            {Object.entries(s.month_factors)
              .map(([m, f]) => `${month(m)} — ${Math.round(f * 100)}%`)
              .join(', ')}
          </Text>

          <Tabs defaultValue="items">
            <Tabs.List>
              <Tabs.Tab value="items">Что фасовать</Tabs.Tab>
              <Tabs.Tab value="materials">Дефицит материалов ({s.materials_short})</Tabs.Tab>
              <Tabs.Tab value="nfp">Дефицит НФП ({run.nfp.length})</Tabs.Tab>
            </Tabs.List>

            <Tabs.Panel value="items" pt="md">
              <Group mb="sm">
                <SegmentedControl
                  value={scope}
                  onChange={(v) => setScope(v as 'need' | 'all')}
                  data={[
                    { value: 'need', label: `К фасовке (${s.items_needed})` },
                    { value: 'all', label: `Все (${s.items})` },
                  ]}
                />
                <TextInput placeholder="Поиск по ГП или НФП" value={search} onChange={(e) => setSearch(e.currentTarget.value)} w={320} />
              </Group>
              <Table striped highlightOnHover fz="sm">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>№</Table.Th>
                    <Table.Th>ГП</Table.Th>
                    <Table.Th>ABC</Table.Th>
                    <Table.Th>Кончится</Table.Th>
                    <Table.Th ta="right">План на горизонт</Table.Th>
                    <Table.Th ta="right">Запас ГП</Table.Th>
                    <Table.Th ta="right">Заказы</Table.Th>
                    <Table.Th ta="right">Потребность</Table.Th>
                    <Table.Th ta="right">Можно сейчас</Table.Th>
                    <Table.Th w={150}>Статус</Table.Th>
                    <Table.Th>Что ограничивает</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {lines.map((l) => (
                    <Table.Tr key={l.item}>
                      <Table.Td>{l.priority}</Table.Td>
                      <Table.Td>
                        <Text size="sm">{l.item}</Text>
                        <Text size="xs" c="dimmed">
                          {l.line_group}
                        </Text>
                      </Table.Td>
                      <Table.Td>{l.abc}</Table.Td>
                      <Table.Td>{month(l.stockout_month)}</Table.Td>
                      <Table.Td ta="right">{num.format(l.plan_horizon)}</Table.Td>
                      <Table.Td ta="right">{num.format(l.gp_stock)}</Table.Td>
                      <Table.Td ta="right">{num.format(l.open_orders)}</Table.Td>
                      <Table.Td ta="right" fw={600}>
                        {num.format(l.need)}
                      </Table.Td>
                      <Table.Td ta="right">{num.format(l.feasible)}</Table.Td>
                      <Table.Td>
                        <Badge variant="light" color={STATUS_COLOR[l.status]}>
                          {l.status}
                        </Badge>
                      </Table.Td>
                      <Table.Td>
                        {l.limit === 'НФП' ? (
                          <Text size="sm">
                            НФП: есть {kg.format(l.nfp_available_kg)} из {kg.format(l.nfp_need_kg)} кг
                            {l.nfp_quarantine_kg > 0 && `, на карантине ${kg.format(l.nfp_quarantine_kg)}`}
                          </Text>
                        ) : (
                          <Text size="sm">{l.limit ?? ''}</Text>
                        )}
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Tabs.Panel>

            <Tabs.Panel value="materials" pt="md">
              <Table striped fz="sm">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Материал</Table.Th>
                    <Table.Th ta="right">Нужно</Table.Th>
                    <Table.Th ta="right">На складе</Table.Th>
                    <Table.Th ta="right">Дефицит</Table.Th>
                    <Table.Th>Для каких ГП</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {run.materials
                    .filter((m) => m.shortage > 0)
                    .map((m) => (
                      <Table.Tr key={m.material}>
                        <Table.Td>{m.material}</Table.Td>
                        <Table.Td ta="right">{kg.format(m.need)}</Table.Td>
                        <Table.Td ta="right">{kg.format(m.available)}</Table.Td>
                        <Table.Td ta="right" c="red" fw={600}>
                          {kg.format(m.shortage)}
                        </Table.Td>
                        <Table.Td>
                          <Text size="xs">{m.item_names}</Text>
                        </Table.Td>
                      </Table.Tr>
                    ))}
                </Table.Tbody>
              </Table>
            </Tabs.Panel>

            <Tabs.Panel value="nfp" pt="md">
              <Text size="sm" c="dimmed" mb="sm">
                Что выпустить на 1 ступени: потребность в НФП минус доступный НФП и НФП на карантине (5 рабочих дней).
              </Text>
              <Table striped fz="sm">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>НФП</Table.Th>
                    <Table.Th>Фракция / назначение</Table.Th>
                    <Table.Th ta="right">Нужно, кг</Table.Th>
                    <Table.Th ta="right">Доступно</Table.Th>
                    <Table.Th ta="right">Карантин</Table.Th>
                    <Table.Th ta="right">Выпустить, кг</Table.Th>
                    <Table.Th>Для каких ГП</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {run.nfp.map((n) => (
                    <Table.Tr key={`${n.nfp}|${n.characteristic}|${n.purpose}`}>
                      <Table.Td>{n.nfp}</Table.Td>
                      <Table.Td>
                        <Text size="sm">{n.characteristic}</Text>
                        <Text size="xs" c="dimmed">
                          {n.purpose}
                        </Text>
                      </Table.Td>
                      <Table.Td ta="right">{kg.format(n.need_kg)}</Table.Td>
                      <Table.Td ta="right">{kg.format(n.available_kg)}</Table.Td>
                      <Table.Td ta="right">
                        {kg.format(n.quarantine_kg)}
                        {n.quarantine_ready && (
                          <Text size="xs" c="dimmed">
                            до {dmy(n.quarantine_ready)}
                          </Text>
                        )}
                      </Table.Td>
                      <Table.Td ta="right" fw={600}>
                        {kg.format(n.shortage_kg)}
                      </Table.Td>
                      <Table.Td>
                        <Text size="xs">{n.items}</Text>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Tabs.Panel>
          </Tabs>
        </>
      )}
    </Stack>
  )
}
