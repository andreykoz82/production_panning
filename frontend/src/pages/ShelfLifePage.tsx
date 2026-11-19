// Анализ сроков годности ГП: запас по сериям, продажи по плану (FEFO), производство и наработка,
// уход в неликвид при остаточном сроке ниже порога.

import { BarChart, CompositeChart } from '@mantine/charts'
import {
  Alert,
  Badge,
  Box,
  Chip,
  Drawer,
  Group,
  Loader,
  NumberInput,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import {
  IconAlertTriangle,
  IconBuildingFactory2,
  IconChevronDown,
  IconChevronUp,
  IconHourglass,
  IconHourglassLow,
  IconPackages,
  IconSelector,
  IconShoppingCartOff,
} from '@tabler/icons-react'
import { useEffect, useMemo, useState } from 'react'

import { shelfApi, type ShelfAnalysis, type ShelfItem, type ShelfLot, type ShelfParams, type ShelfStatus } from '../api'
import { PageHeader, Section, StatCard } from '../ui'

const num = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const short = (v: number) =>
  Math.abs(v) >= 1e6 ? `${(v / 1e6).toFixed(1)} млн` : Math.abs(v) >= 1e3 ? `${Math.round(v / 1e3)} тыс` : num.format(v)
const dmy = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString('ru-RU') : '—')
const monthLabel = (iso: string) =>
  new Date(iso).toLocaleDateString('ru-RU', { month: 'short', year: '2-digit' }).replace('.', '')

const STATUS_COLOR: Record<ShelfStatus, string> = {
  'Неликвид есть': 'red',
  'Уйдёт в неликвид': 'orange',
  'Не хватит': 'yellow',
  Норма: 'gray',
}

const DEFAULTS: ShelfParams = {
  horizon_months: 12,
  fulfillment_pct: 100,
  threshold_pct: 70,
  replenish: true,
  cover_months: 3,
  bottling: true,
}

type SortKey =
  | 'item'
  | 'shelf_life_months'
  | 'stock'
  | 'monthly_demand'
  | 'coverage_months'
  | 'illiquid_now'
  | 'illiquid_forecast'
  | 'illiquid_total'
  | 'produced'
  | 'lost_sales'

const sortValue = (i: ShelfItem, key: SortKey): number | string =>
  key === 'produced' ? i.produced_orders + i.produced_planned : (i[key] ?? -1)

export default function ShelfLifePage() {
  const [params, setParams] = useState<ShelfParams>(DEFAULTS)
  const [debounced] = useDebouncedValue(params, 400)
  const [data, setData] = useState<ShelfAnalysis | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [statuses, setStatuses] = useState<ShelfStatus[]>([])
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: 'illiquid_total', desc: true })

  useEffect(() => {
    setLoading(true)
    shelfApi
      .analyze(debounced)
      .then((d) => {
        setData(d)
        setError(null)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [debounced])

  const set = <K extends keyof ShelfParams>(key: K, value: ShelfParams[K]) => setParams((p) => ({ ...p, [key]: value }))

  const counts = useMemo(() => {
    const c = new Map<ShelfStatus, number>()
    for (const i of data?.items ?? []) c.set(i.status, (c.get(i.status) ?? 0) + 1)
    return c
  }, [data])
  const rows = useMemo(() => {
    const q = search.trim().toLowerCase()
    const dir = sort.desc ? -1 : 1
    return (data?.items ?? [])
      .filter((i) => (!statuses.length || statuses.includes(i.status)) && (!q || i.item.toLowerCase().includes(q)))
      .sort((a, b) => {
        const va = sortValue(a, sort.key)
        const vb = sortValue(b, sort.key)
        const c = typeof va === 'string' ? va.localeCompare(String(vb), 'ru') : va - (vb as number)
        return c * dir || b.illiquid_total - a.illiquid_total || a.item.localeCompare(b.item, 'ru')
      })
  }, [data, statuses, search, sort])
  const th = (key: SortKey, label: string, right = true) => (
    <SortTh
      label={label}
      right={right}
      active={sort.key === key}
      desc={sort.desc}
      onClick={() => setSort((s) => ({ key, desc: s.key === key ? !s.desc : key !== 'item' }))}
    />
  )

  const chart = useMemo(
    () =>
      (data?.months ?? []).map((m) => ({
        month: monthLabel(m.month),
        Продажи: m.sales,
        'Производство: заказы': m.orders,
        'Производство: наработка': m.planned,
        'Ликвидный запас': m.liquid_end,
        Неликвид: m.illiquid,
        'Неликвид накопленный': m.illiquid_end,
      })),
    [data],
  )

  const s = data?.summary

  return (
    <Stack gap="md">
      <PageHeader
        title="Сроки годности ГП"
        icon={<IconHourglass size={24} />}
        description="Что успеем продать, а что уйдёт в неликвид. Запас — по сериям со склада ГП и опта; продажи — план × процент выполнения, сначала серии с меньшим сроком годности (FEFO); серия становится неликвидной, когда остаточный срок годности опускается ниже порога. Учитываются открытые этапы (по графику, с сертификацией) и будущая наработка. СТМ не входит в анализ — производится только по письму клиента."
      />

      <Section>
        <Group align="flex-end" gap="lg">
          <NumberInput
            label="Выполнение плана продаж, %"
            value={params.fulfillment_pct}
            onChange={(v) => set('fulfillment_pct', Number(v) || 0)}
            min={0}
            max={300}
            step={5}
            w={200}
          />
          <NumberInput
            label="Неликвид, если остаточный срок ниже, %"
            value={params.threshold_pct}
            onChange={(v) => set('threshold_pct', Number(v) || 0)}
            min={0}
            max={100}
            step={5}
            w={260}
          />
          <Select
            label="Горизонт"
            value={String(params.horizon_months)}
            onChange={(v) => v && set('horizon_months', Number(v))}
            data={['6', '12', '18', '24'].map((v) => ({ value: v, label: `${v} мес.` }))}
            w={120}
            allowDeselect={false}
          />
          <Stack gap={6}>
            <Switch
              label="Учитывать будущую наработку"
              checked={params.replenish}
              onChange={(e) => set('replenish', e.currentTarget.checked)}
            />
            <Group gap={6}>
              <Text size="sm" c={params.replenish ? undefined : 'dimmed'}>
                серия на
              </Text>
              <NumberInput
                size="xs"
                w={70}
                value={params.cover_months}
                onChange={(v) => set('cover_months', Number(v) || 1)}
                min={0.5}
                max={12}
                step={0.5}
                disabled={!params.replenish}
              />
              <Text size="sm" c={params.replenish ? undefined : 'dimmed'}>
                мес. продаж, не меньше мин. серии
              </Text>
            </Group>
          </Stack>
          <Switch
            label="Учитывать розлив"
            description="Стоматофит, Бронхофитол, НЮДА"
            checked={params.bottling}
            onChange={(e) => set('bottling', e.currentTarget.checked)}
          />
          {loading && <Loader size="sm" />}
        </Group>
        {data?.report_date && (
          <Text size="xs" c="dimmed" mt="sm">
            Остатки по сериям на {dmy(data.report_date)} · {s?.lots} серий в анализе
            {s?.items_bottling ? ` · розлив: ${s.items_bottling} поз.` : ''}
            {s?.lots_out_of_scope
              ? ` · ${s.lots_out_of_scope} серий не учитываются (СТМ, экспериментальные, образцы${params.bottling ? '' : ', розлив'})`
              : ''}
          </Text>
        )}
      </Section>

      {error && <Alert color="red">{error}</Alert>}

      {s && (
        <SimpleGrid cols={{ base: 2, lg: 5 }}>
          <StatCard
            icon={<IconPackages size={20} />}
            label="Запас ГП"
            value={short(s.stock)}
            hint={`${num.format(s.stock)} шт · ${s.lots} серий`}
          />
          <StatCard
            icon={<IconHourglassLow size={20} />}
            color="red"
            label="Неликвид сейчас"
            value={short(s.illiquid_now)}
            hint={`${s.items_illiquid_now} поз. · остаточный срок < ${params.threshold_pct} %`}
          />
          <StatCard
            icon={<IconAlertTriangle size={20} />}
            color="orange"
            label={`Уйдёт в неликвид за ${params.horizon_months} мес.`}
            value={short(s.illiquid_forecast)}
            hint={`${s.items_at_risk} поз. · ${s.sales ? ((s.illiquid_forecast / s.sales) * 100).toFixed(1) : 0} % от продаж`}
          />
          <StatCard
            icon={<IconBuildingFactory2 size={20} />}
            color="blue"
            label="Будет произведено"
            value={short(s.produced_orders + s.produced_planned)}
            hint={`заказы ${short(s.produced_orders)} + наработка ${short(s.produced_planned)}`}
          />
          <StatCard
            icon={<IconShoppingCartOff size={20} />}
            color="yellow"
            label="Не хватит для продаж"
            value={short(s.lost_sales)}
            hint={`${s.demand ? ((s.lost_sales / s.demand) * 100).toFixed(1) : 0} % плана`}
          />
        </SimpleGrid>
      )}

      {data && (
        <SimpleGrid cols={{ base: 1, lg: 3 }}>
          <Box style={{ gridColumn: 'span 2' }}>
            <Section
              title="Движение запаса по месяцам"
              description="Продажи, производство и ликвидный запас на конец месяца, шт"
            >
              <CompositeChart
                h={300}
                data={chart}
                dataKey="month"
                withLegend
                legendProps={{ verticalAlign: 'bottom' }}
                valueFormatter={(v) => num.format(v)}
                yAxisProps={{ tickFormatter: (v: number) => short(v), width: 70 }}
                maxBarWidth={26}
                series={[
                  { name: 'Ликвидный запас', color: 'brand.2', type: 'area' },
                  { name: 'Продажи', color: 'gray.6', type: 'bar' },
                  { name: 'Производство: заказы', color: 'blue.6', type: 'bar' },
                  { name: 'Производство: наработка', color: 'cyan.4', type: 'bar' },
                ]}
                curveType="monotone"
              />
            </Section>
          </Box>
          <Section title="Уходит в неликвид" description="Шт за месяц; линия — накопленный неликвид">
            <CompositeChart
              h={300}
              data={chart}
              dataKey="month"
              valueFormatter={(v) => num.format(v)}
              yAxisProps={{ tickFormatter: (v: number) => short(v), width: 60 }}
              maxBarWidth={22}
              series={[
                { name: 'Неликвид', color: 'red.6', type: 'bar' },
                { name: 'Неликвид накопленный', color: 'red.3', type: 'line' },
              ]}
            />
          </Section>
        </SimpleGrid>
      )}

      {data && (
        <Section p={0}>
          <Group p="md" pb="xs" justify="space-between">
            <Chip.Group multiple value={statuses} onChange={(v) => setStatuses(v as ShelfStatus[])}>
              <Group gap="xs">
                {(Object.keys(STATUS_COLOR) as ShelfStatus[])
                  .filter((st) => counts.get(st))
                  .map((st) => (
                    <Chip key={st} value={st} size="sm" color={STATUS_COLOR[st]} variant="light">
                      {st} ({counts.get(st)})
                    </Chip>
                  ))}
              </Group>
            </Chip.Group>
            <TextInput
              placeholder="Поиск ГП"
              value={search}
              onChange={(e) => setSearch(e.currentTarget.value)}
              w={280}
            />
          </Group>
          <Table fz="sm">
            <Table.Thead>
              <Table.Tr>
                {th('item', 'ГП', false)}
                {th('shelf_life_months', 'Срок, мес')}
                {th('stock', 'Запас')}
                {th('monthly_demand', 'Продажи / мес')}
                {th('coverage_months', 'Хватит, мес')}
                {th('illiquid_now', 'Неликвид сейчас')}
                {th('illiquid_forecast', 'Уйдёт в неликвид')}
                {th('illiquid_total', 'Неликвид всего')}
                {th('produced', 'Произведём')}
                {th('lost_sales', 'Не хватит')}
                <Table.Th>Статус</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((i) => (
                <ItemRow key={i.item} i={i} onOpen={() => setSelected(i.item)} />
              ))}
            </Table.Tbody>
          </Table>
        </Section>
      )}

      <ItemDrawer item={selected} params={debounced} onClose={() => setSelected(null)} />
    </Stack>
  )
}

function SortTh({
  label,
  right,
  active,
  desc,
  onClick,
}: {
  label: string
  right: boolean
  active: boolean
  desc: boolean
  onClick: () => void
}) {
  const Icon = !active ? IconSelector : desc ? IconChevronDown : IconChevronUp
  return (
    <Table.Th
      ta={right ? 'right' : undefined}
      onClick={onClick}
      style={{ cursor: 'pointer', userSelect: 'none', whiteSpace: 'normal', verticalAlign: 'bottom' }}
    >
      <Text span size="sm" fw={active ? 700 : 600} c={active ? undefined : 'dimmed'}>
        {label}
        <Icon size={13} stroke={1.8} style={{ marginLeft: 2, verticalAlign: '-2px' }} />
      </Text>
    </Table.Th>
  )
}

function ItemRow({ i, onOpen }: { i: ShelfItem; onOpen: () => void }) {
  return (
    <Table.Tr style={{ cursor: 'pointer' }} onClick={onOpen}>
      <Table.Td>
        {i.bottling && (
          <Badge size="xs" color="grape" variant="light" mr={6}>
            розлив
          </Badge>
        )}
        {i.item}
      </Table.Td>
      <Table.Td ta="right">{i.shelf_life_months ?? '—'}</Table.Td>
      <Table.Td ta="right">
        {num.format(i.stock)}
        <Text size="xs" c="dimmed">
          {i.lots} сер.
        </Text>
      </Table.Td>
      <Table.Td ta="right">{num.format(i.monthly_demand)}</Table.Td>
      <Table.Td ta="right">{i.coverage_months ?? '—'}</Table.Td>
      <Table.Td ta="right" c={i.illiquid_now ? 'red' : 'dimmed'} fw={i.illiquid_now ? 600 : undefined}>
        {i.illiquid_now ? num.format(i.illiquid_now) : '—'}
      </Table.Td>
      <Table.Td ta="right" c={i.illiquid_forecast ? 'orange.8' : 'dimmed'}>
        {i.illiquid_forecast ? (
          <>
            <Text size="sm" fw={600}>
              {num.format(i.illiquid_forecast)}
            </Text>
            <Text size="xs" c="dimmed">
              с {dmy(i.first_illiquid)}
            </Text>
          </>
        ) : (
          '—'
        )}
      </Table.Td>
      <Table.Td ta="right" c={i.illiquid_total ? 'red.8' : 'dimmed'} fw={i.illiquid_total ? 700 : undefined}>
        {i.illiquid_total ? num.format(i.illiquid_total) : '—'}
      </Table.Td>
      <Table.Td ta="right">
        {i.produced_orders + i.produced_planned ? num.format(i.produced_orders + i.produced_planned) : '—'}
      </Table.Td>
      <Table.Td ta="right" c={i.lost_sales ? 'yellow.8' : 'dimmed'}>
        {i.lost_sales ? num.format(i.lost_sales) : '—'}
      </Table.Td>
      <Table.Td miw={150} style={{ whiteSpace: 'nowrap' }}>
        <Badge color={STATUS_COLOR[i.status]} styles={{ label: { overflow: 'visible' } }}>
          {i.status}
        </Badge>
      </Table.Td>
    </Table.Tr>
  )
}

function ItemDrawer({ item, params, onClose }: { item: string | null; params: ShelfParams; onClose: () => void }) {
  const [detail, setDetail] = useState<ShelfAnalysis['detail']>(null)
  useEffect(() => {
    if (!item) return
    setDetail(null)
    shelfApi.analyze(params, item).then((d) => setDetail(d.detail))
  }, [item, params])

  const points = useMemo(
    () =>
      (detail?.points ?? []).map((p) => ({
        date: new Date(p.date).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' }),
        'Ликвидный запас': p.liquid,
        'Неликвид накопленный': p.illiquid,
        Поступление: p.arrived,
        Продажи: p.sold,
        'Не хватило': p.lost,
      })),
    [detail],
  )

  return (
    <Drawer opened={!!item} onClose={onClose} position="right" size="80%" title={<Text fw={650}>{item}</Text>}>
      {!detail ? (
        <Loader />
      ) : (
        <Stack gap="md">
          <Group gap="xl">
            <Text size="sm">
              Запас <b>{num.format(detail.row.stock)}</b> шт · продажи <b>{num.format(detail.row.monthly_demand)}</b> в
              мес. · срок годности {detail.row.shelf_life_months ?? '—'} мес.
            </Text>
            <Badge color={STATUS_COLOR[detail.row.status]}>{detail.row.status}</Badge>
          </Group>
          <Section
            title="Запас по неделям"
            description="Ликвидный запас и неликвид на конец недели; столбцы — поступление и продажи за неделю"
          >
            <CompositeChart
              h={280}
              data={points}
              dataKey="date"
              withLegend
              legendProps={{ verticalAlign: 'bottom' }}
              valueFormatter={(v) => num.format(v)}
              yAxisProps={{ tickFormatter: (v: number) => short(v), width: 60 }}
              maxBarWidth={10}
              curveType="stepAfter"
              series={[
                { name: 'Ликвидный запас', color: 'brand.3', type: 'area' },
                { name: 'Неликвид накопленный', color: 'red.5', type: 'area' },
                { name: 'Поступление', color: 'blue.6', type: 'bar' },
                { name: 'Продажи', color: 'gray.5', type: 'bar' },
                { name: 'Не хватило', color: 'yellow.6', type: 'bar' },
              ]}
            />
          </Section>
          <Section
            title="Серии на шкале времени"
            description="Сверху — серии с наибольшим неликвидом. Зелёным — пока серия продаётся; бордовая черта — дата, когда остаточный срок опустится ниже порога; красным — непроданный остаток, ушедший в неликвид"
          >
            <LotsTimeline lots={detail.lots} from={detail.points[0]?.date} to={detail.points.at(-1)?.date} />
          </Section>
          <Section title="Помесячно" p={0}>
            <BarChart
              h={200}
              p="md"
              data={detail.months.map((m) => ({
                month: monthLabel(m.month),
                Продажи: m.sales,
                'Не хватило': m.lost,
                Неликвид: m.illiquid,
              }))}
              dataKey="month"
              type="stacked"
              valueFormatter={(v) => num.format(v)}
              series={[
                { name: 'Продажи', color: 'gray.5' },
                { name: 'Не хватило', color: 'yellow.6' },
                { name: 'Неликвид', color: 'red.6' },
              ]}
            />
          </Section>
        </Stack>
      )}
    </Drawer>
  )
}

const SOURCE_COLOR: Record<ShelfLot['source'], string> = { склад: 'gray', заказ: 'blue', наработка: 'cyan' }

function LotsTimeline({ lots, from, to }: { lots: ShelfLot[]; from?: string; to?: string }) {
  if (!from || !to) return null
  const t0 = new Date(from).getTime()
  const t1 = new Date(to).getTime()
  const pos = (iso: string | null) =>
    iso ? Math.min(100, Math.max(0, ((new Date(iso).getTime() - t0) / (t1 - t0)) * 100)) : 100
  const months: string[] = []
  // подписи — с первого числа каждого месяца после даты расчёта
  for (let d = new Date(new Date(from).getFullYear(), new Date(from).getMonth() + 1, 1); d.getTime() <= t1;) {
    months.push(d.toISOString())
    d = new Date(d.getFullYear(), d.getMonth() + 1, 1)
  }
  return (
    <Box>
      <Box pos="relative" h={18} ml={260} mb={4}>
        {months.map((m) => (
          <Text key={m} size="xs" c="dimmed" pos="absolute" left={`${pos(m)}%`} style={{ whiteSpace: 'nowrap' }}>
            {monthLabel(m)}
          </Text>
        ))}
      </Box>
      <Stack gap={4}>
        {lots.map((lot, k) => {
          const start = pos(lot.available)
          const end = pos(lot.illiquid_date ?? lot.sold_out ?? to)
          const cut = pos(lot.illiquid_from)
          return (
            <Group key={`${lot.series}-${k}`} gap={8} wrap="nowrap" align="center">
              <Box w={252} style={{ flexShrink: 0 }}>
                <Group gap={6} wrap="nowrap">
                  <Badge size="xs" color={SOURCE_COLOR[lot.source]}>
                    {lot.source}
                  </Badge>
                  <Text size="xs" fw={500} truncate>
                    {lot.series}
                  </Text>
                </Group>
                <Text size="xs" c="dimmed" truncate>
                  {num.format(lot.qty)} шт · до {dmy(lot.expiry)} · {Math.round(lot.residual_pct)}%
                </Text>
              </Box>
              <Tooltip
                multiline
                w={320}
                label={
                  <>
                    Произведена {dmy(lot.production)}, в продаже с {dmy(lot.available)}
                    <br />
                    Неликвид с {dmy(lot.illiquid_from)} · годен до {dmy(lot.expiry)}
                    <br />
                    Продано {num.format(lot.sold)}
                    {lot.sold_out ? `, распродана ${dmy(lot.sold_out)}` : ''}
                    {lot.illiquid_qty ? (
                      <>
                        <br />В неликвид: {num.format(lot.illiquid_qty)} шт ({dmy(lot.illiquid_date)})
                      </>
                    ) : null}
                    {lot.left ? (
                      <>
                        <br />
                        Останется на конец горизонта: {num.format(lot.left)}
                      </>
                    ) : null}
                  </>
                }
              >
                <Box
                  pos="relative"
                  h={18}
                  style={{ flex: 1, background: 'var(--mantine-color-gray-0)', borderRadius: 4 }}
                >
                  {lot.illiquid_qty > 0 && lot.illiquid_date === lot.available ? null : (
                    <Box
                      pos="absolute"
                      top={2}
                      h={14}
                      left={`${start}%`}
                      w={`${Math.max(0.5, end - start)}%`}
                      bg={lot.source === 'наработка' ? 'cyan.3' : lot.source === 'заказ' ? 'blue.3' : 'brand.3'}
                      style={{ borderRadius: 3 }}
                    />
                  )}
                  {lot.illiquid_qty > 0 && (
                    <Box
                      pos="absolute"
                      top={2}
                      h={14}
                      left={`${pos(lot.illiquid_date)}%`}
                      w={`${Math.max(0.8, 100 - pos(lot.illiquid_date))}%`}
                      bg="red.5"
                      style={{ borderRadius: 3 }}
                    >
                      <Text size="10px" c="white" fw={600} px={4} truncate>
                        {num.format(lot.illiquid_qty)}
                      </Text>
                    </Box>
                  )}
                  {cut > 0 && cut < 100 && <Box pos="absolute" top={0} h={18} w={2} left={`${cut}%`} bg="#8c1c3c" />}
                </Box>
              </Tooltip>
            </Group>
          )
        })}
      </Stack>
    </Box>
  )
}
