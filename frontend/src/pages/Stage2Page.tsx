import {
  Alert,
  Badge,
  Button,
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
} from '@mantine/core'
import { useCallback, useEffect, useMemo, useState } from 'react'

import {
  IconAlertTriangle,
  IconBox,
  IconCalculator,
  IconClipboardList,
  IconDownload,
  IconLeaf,
  IconMail,
  IconPackages,
} from '@tabler/icons-react'

import { planningApi, type PlanRun, type PlanRunDetail, type Stage2Status } from '../api'
import { PageHeader, Section, StatCard } from '../ui'

const num = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const kg = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
const today = () => new Date().toISOString().slice(0, 10)
const month = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString('ru-RU', { month: 'short', year: 'numeric' }) : 'не кончится'
const dmy = (iso: string) => new Date(iso).toLocaleDateString('ru-RU')

const WAREHOUSE_ROLE: Record<string, string> = {
  gp_cert: 'ГП на сертификации',
  gp_sale: 'ГП к продаже',
  nfp: 'НФП',
  nfp_quarantine: 'НФП на карантине',
  byproducts: 'ПП',
  raw: 'сырьё',
  materials: 'упаковка',
}

const STATUS_COLOR: Record<Stage2Status, string> = {
  'Можно фасовать': 'teal',
  Частично: 'yellow',
  Нельзя: 'red',
  'Нет данных': 'gray',
  'Не требуется': 'gray',
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
      (l) => !l.stm && (scope === 'all' || l.need > 0) && (!q || `${l.item} ${l.nfp ?? ''}`.toLowerCase().includes(q)),
    )
  }, [run, scope, search])
  const stmLines = useMemo(() => (run ? run.lines.filter((l) => l.stm) : []), [run])

  const s = run?.summary

  return (
    <Stack>
      <PageHeader
        title="Потребность 2 ступени"
        icon={<IconClipboardList size={24} />}
        description="Сколько фасовать, чтобы обеспечить план продаж на N месяцев: план − запас ГП (склад ГП + опт) − открытые заказы, не меньше выпуска линии за 1 ч. Из текущего месяца — оставшиеся рабочие дни."
        actions={
          run && (
            <Button
              component="a"
              href={planningApi.exportUrl(run.id)}
              variant="default"
              leftSection={<IconDownload size={16} />}
            >
              Excel для диспетчера
            </Button>
          )
        }
      />

      <Section>
        <Group align="flex-end">
          <NumberInput
            label="Горизонт, мес."
            min={1}
            max={24}
            w={140}
            value={horizon}
            onChange={(v) => setHorizon(Number(v) || 1)}
          />
          <TextInput
            label="Дата расчёта"
            type="date"
            w={170}
            value={calcDate}
            onChange={(e) => setCalcDate(e.currentTarget.value)}
          />
          <Button loading={busy} onClick={calculate} leftSection={<IconCalculator size={16} />}>
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
        </Group>
      </Section>

      {error && (
        <Alert color="red" title="Не удалось рассчитать">
          {error}
        </Alert>
      )}
      {!run && !error && <Text c="dimmed">Расчётов ещё нет — задайте горизонт и нажмите «Рассчитать».</Text>}

      {run && s && (
        <>
          <SimpleGrid cols={{ base: 2, md: 4 }}>
            <StatCard
              icon={<IconPackages size={20} />}
              label="Позиций к фасовке"
              value={`${s.items_needed} из ${s.items}`}
              hint={`полностью ${s.items_full}, частично ${s.items_partial}, нельзя ${s.items_blocked}${
                s.stm_items ? ` · СТМ отдельно: ${s.stm_items}` : ''
              }`}
            />
            <StatCard
              icon={<IconBox size={20} />}
              color="blue"
              label="Потребность, шт"
              value={num.format(s.need_units)}
              hint={`можно выпустить сейчас ${num.format(s.feasible_units)}`}
            />
            <StatCard
              icon={<IconAlertTriangle size={20} />}
              color={s.materials_short ? 'red' : 'brand'}
              label="Материалов в дефиците"
              value={s.materials_short}
              hint="нехватка до 10 % — не дефицит"
            />
            <StatCard
              icon={<IconLeaf size={20} />}
              color="orange"
              label="Выпустить НФП на 1 ступени"
              value={`${num.format(s.nfp_shortage_kg)} кг`}
              hint={
                s.nfp_uncovered_kg != null
                  ? `в заказах 1 ступени ${num.format(s.nfp_stage1_orders_kg ?? 0)}, не покрыто ${num.format(s.nfp_uncovered_kg)}`
                  : 'с учётом карантина'
              }
            />
          </SimpleGrid>
          {s.warehouses && (
            <Text size="xs" c="dimmed">
              Учтены склады:{' '}
              {Object.entries(s.warehouses)
                .map(([role, names]) => `${WAREHOUSE_ROLE[role] ?? role} — ${names.join(', ')}`)
                .join('; ')}
            </Text>
          )}
          <Text size="xs" c="dimmed">
            Доля плана в горизонте:{' '}
            {Object.entries(s.month_factors)
              .map(([m, f]) => `${month(m)} — ${Math.round(f * 100)}%`)
              .join(', ')}
          </Text>

          <Tabs defaultValue="items">
            <Tabs.List>
              <Tabs.Tab value="items" leftSection={<IconPackages size={16} />}>
                Что фасовать
              </Tabs.Tab>
              <Tabs.Tab value="materials" leftSection={<IconBox size={16} />}>
                Дефицит материалов ({s.materials_short})
              </Tabs.Tab>
              <Tabs.Tab value="nfp" leftSection={<IconLeaf size={16} />}>
                Дефицит НФП ({run.nfp.length})
              </Tabs.Tab>
              {stmLines.length > 0 && (
                <Tabs.Tab value="stm" leftSection={<IconMail size={16} />} color="violet">
                  СТМ — по письму клиента ({stmLines.length})
                </Tabs.Tab>
              )}
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
                <TextInput
                  placeholder="Поиск по ГП или НФП"
                  value={search}
                  onChange={(e) => setSearch(e.currentTarget.value)}
                  w={320}
                />
              </Group>
              <Section p={0}>
                <Table fz="sm" stickyHeader>
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
              </Section>
            </Tabs.Panel>

            <Tabs.Panel value="stm" pt="md">
              <Alert color="violet" variant="light" mb="sm" icon={<IconMail size={18} />}>
                СТМ (ТМ «Будь здоров!») фасуется только после письма клиента, поэтому план продаж здесь — прогноз, а не
                задание. В расчёте СТМ идёт после всех наших позиций: «Можно выпустить при заказе» — из НФП и упаковки,
                которые остались. В сводку, дефицит материалов и задание 1 ступени СТМ не входит. Заказ, поставленный в
                1С по письму, попадает на график как обычно — с пометкой СТМ.
              </Alert>
              <Section p={0}>
                <Table fz="sm">
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>ГП</Table.Th>
                      <Table.Th>ABC</Table.Th>
                      <Table.Th>Кончится</Table.Th>
                      <Table.Th ta="right">Прогноз на горизонт</Table.Th>
                      <Table.Th ta="right">Запас ГП</Table.Th>
                      <Table.Th ta="right">В заказах</Table.Th>
                      <Table.Th ta="right">Не хватит по прогнозу</Table.Th>
                      <Table.Th ta="right">Можно выпустить при заказе</Table.Th>
                      <Table.Th>Что ограничивает</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {stmLines.map((l) => (
                      <Table.Tr key={l.item}>
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
                        <Table.Td ta="right">
                          {l.open_orders > 0 ? (
                            <Badge color="violet">{num.format(l.open_orders)}</Badge>
                          ) : (
                            <Text size="sm" c="dimmed">
                              ждёт письма
                            </Text>
                          )}
                        </Table.Td>
                        <Table.Td ta="right" fw={600}>
                          {l.need > 0 ? num.format(l.need) : '—'}
                        </Table.Td>
                        <Table.Td ta="right">{l.need > 0 ? num.format(l.feasible) : '—'}</Table.Td>
                        <Table.Td>
                          {l.limit === 'НФП' ? (
                            <Text size="sm">
                              НФП: осталось {kg.format(l.nfp_available_kg)} из {kg.format(l.nfp_need_kg)} кг
                            </Text>
                          ) : (
                            <Text size="sm">{l.limit ?? ''}</Text>
                          )}
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Section>
            </Tabs.Panel>

            <Tabs.Panel value="materials" pt="md">
              <Section p={0}>
                <Table fz="sm">
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Материал</Table.Th>
                      <Table.Th ta="right">Нужно</Table.Th>
                      <Table.Th ta="right">На складе</Table.Th>
                      <Table.Th ta="right">Дефицит</Table.Th>
                      <Table.Th ta="right">Не хватает</Table.Th>
                      <Table.Th>Для каких ГП</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {run.materials
                      .filter((m) => m.shortage > 0 || m.within_tolerance)
                      .map((m) => (
                        <Table.Tr key={m.material} opacity={m.within_tolerance ? 0.75 : 1}>
                          <Table.Td>
                            {m.material}
                            {m.within_tolerance && (
                              <Badge ml="xs" size="xs" color="gray">
                                в пределах 10 %
                              </Badge>
                            )}
                          </Table.Td>
                          <Table.Td ta="right">{kg.format(m.need)}</Table.Td>
                          <Table.Td ta="right">{kg.format(m.available)}</Table.Td>
                          <Table.Td ta="right" c={m.shortage > 0 ? 'red' : 'dimmed'} fw={600}>
                            {m.shortage > 0 ? kg.format(m.shortage) : '—'}
                          </Table.Td>
                          <Table.Td ta="right">{m.deviation_pct != null ? `${m.deviation_pct}%` : ''}</Table.Td>
                          <Table.Td>
                            <Text size="xs">{m.item_names}</Text>
                          </Table.Td>
                        </Table.Tr>
                      ))}
                  </Table.Tbody>
                </Table>
              </Section>
            </Tabs.Panel>

            <Tabs.Panel value="nfp" pt="md">
              <Text size="sm" c="dimmed" mb="sm">
                Что выпустить на 1 ступени: потребность в НФП минус доступный НФП и НФП на карантине (5 рабочих дней),
                округлено до 100 кг. Открытые заказы 1 ступени той же фракции уменьшают «Не покрыто».
              </Text>
              <Section p={0}>
                <Table fz="sm">
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>НФП</Table.Th>
                      <Table.Th>Фракция / назначение</Table.Th>
                      <Table.Th ta="right">Нужно, кг</Table.Th>
                      <Table.Th ta="right">Доступно</Table.Th>
                      <Table.Th ta="right">Карантин</Table.Th>
                      <Table.Th ta="right">Выпустить, кг</Table.Th>
                      <Table.Th ta="right">В заказах 1 ст.</Table.Th>
                      <Table.Th ta="right">Не покрыто</Table.Th>
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
                        <Table.Td ta="right">{num.format(n.shortage_kg)}</Table.Td>
                        <Table.Td ta="right">{num.format(n.stage1_orders_kg ?? 0)}</Table.Td>
                        <Table.Td ta="right" fw={600} c={(n.uncovered_kg ?? n.shortage_kg) > 0 ? 'red' : undefined}>
                          {num.format(n.uncovered_kg ?? n.shortage_kg)}
                        </Table.Td>
                        <Table.Td>
                          <Text size="xs">{n.items}</Text>
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Section>
            </Tabs.Panel>
          </Tabs>
        </>
      )}
    </Stack>
  )
}
