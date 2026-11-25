import { Alert, Button, Group, Loader, NumberInput, Paper, Stack, Table, Text, TextInput, Title } from '@mantine/core'
import { Fragment, useEffect, useState } from 'react'

type Row = { key: string; name: string; group: string; stock: number; demand: number; monthly: number[]; future: (number | null)[]; products: { name: string; sales: number; qty_per_1000: number; demand: number }[] }
type Calculation = { calendar: string[]; months: string[]; target: string; rows: Row[]; snapshot: number; missing_months: string[]; missing_specs: string[] }
const groups = ['Пачки', 'Конверты', 'Ярлыки', 'Вкладыши']
const month = (date: string) => new Date(date + 'T12:00:00').toLocaleDateString('ru', { month: 'long', year: 'numeric' })
const format = (n: number) => n.toLocaleString('ru')

const units = (value: number) => format(Math.round(value) || 0)
const lotSize = 10_000

function daysOfStock(balance: number, next: number, calendar: string[], demand: (number | null)[]) {
  if (balance <= 0) return 0
  let days = 0
  for (let i = next; i < calendar.length; i++) {
    const volume = demand[i]
    if (volume === null) break
    const start = new Date(calendar[i] + 'T12:00:00')
    const length = new Date(start.getFullYear(), start.getMonth() + 1, 0).getDate()
    if (volume > 0 && balance <= volume) return days + Math.floor(balance * length / volume)
    days += length
    balance -= volume
  }
  return days ? `≥ ${days}` : 'Нет плана'
}

function forecast(row: Row, data: Calculation, receipt: number, order: number) {
  let balance = row.stock
  return data.months.map((date, i) => {
    const opening = balance
    const incoming = (i === 0 ? receipt : 0) + (date === data.target ? order : 0)
    const demand = row.monthly[i]
    balance += incoming - demand
    const coverage = daysOfStock(balance, i + 1, data.calendar, row.future)
    return { date, opening, incoming, demand, balance, coverage }
  })
}

function Order({ data }: { data: Calculation }) {
  const storage = 'printing-receipts:' + data.months[0]
  const [receipts, setReceipts] = useState<Record<string, number>>(() => JSON.parse(localStorage.getItem(storage) || '{}'))
  const [expanded, setExpanded] = useState<string | null>(null)
  const quantity = (r: Row) => Math.max(0, Math.ceil((r.demand - r.stock - (receipts[r.key] || 0)) / lotSize)) * lotSize
  const update = (key: string, value: number) => {
    const next = { ...receipts, [key]: value }
    localStorage.setItem(storage, JSON.stringify(next))
    setReceipts(next)
  }
  const exportOrder = () => {
    const lines = [['Тип материала', 'Материал', 'К заказу, шт.']]
    for (const group of groups) {
      for (const row of data.rows.filter(r => r.group === group && quantity(r) > 0)) {
        lines.push([group, row.name, String(quantity(row))])
      }
    }
    const csv = lines.map(line => line.map(v => '"' + v.replaceAll('"', '""') + '"').join(';')).join('\r\n')
    const url = URL.createObjectURL(new Blob(['\uFEFF', csv], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url
    link.download = 'Заказ типографии ' + data.target.slice(0, 7) + '.csv'
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  return <Stack>
    <Title order={3}>Заказ на {month(data.target)}</Title>
    <Text>Снимок №{data.snapshot}. Расход за период {month(data.months[0])} — {month(data.months[data.months.length - 1])}. Все количества в штуках.</Text>
    {data.missing_months.length > 0 && <Alert color="red">В плане продаж отсутствуют месяцы: {data.missing_months.map(month).join(', ')}. Загрузите полный план.</Alert>}
    {data.missing_specs.length > 0 && <Alert color="orange">В расход не вошли изделия без спецификации: {data.missing_specs.join(', ')}</Alert>}
    <Text size="sm">В поступление внесите только ещё не оприходованную часть предыдущего заказа. Ввод сохраняется в этом браузере по месяцу поступления.</Text>
    <Text size="sm">Расход рассчитан по плану продаж и нормам материалов на 1 000 изделий. Дефицит округляется вверх до партии 10 000 шт. Дни запаса считаются со следующего месяца по будущему плану продаж. Внутри месяца расход распределён равномерно. Знак «≥» означает, что запас покрывает весь доступный непрерывный план.</Text>
    <Button w="fit-content" disabled={!!data.missing_months.length || !data.rows.some(r => quantity(r) > 0)} onClick={exportOrder}>Скачать заказ (CSV)</Button>
    {data.rows.length === 0 && <Text>В спецификациях не найдены печатные материалы выбранных типов.</Text>}
    {groups.map(group => {
      const rows = data.rows.filter(r => r.group === group)
      return rows.length > 0 && <Paper key={group} p="md" withBorder>
        <Title order={4}>{group}</Title>
        <Table.ScrollContainer minWidth={1120}><Table striped stickyHeaderOffset={0}>
          <Table.Thead><Table.Tr><Table.Th>Материал</Table.Th><Table.Th>Доступный остаток</Table.Th>
            <Table.Th>Поступление · {month(data.months[0])}</Table.Th><Table.Th>Расход по плану</Table.Th><Table.Th>К заказу</Table.Th><Table.Th>На конец {data.months[data.months.length - 1].slice(0, 7)}, шт.</Table.Th><Table.Th>Дней продаж</Table.Th><Table.Th>Расчёт</Table.Th>
          </Table.Tr></Table.Thead>
          <Table.Tbody>{rows.map(r => {
            const order = quantity(r)
            const receipt = receipts[r.key] || 0
            const periods = forecast(r, data, receipt, order)
            const last = periods[periods.length - 1]
            const open = expanded === r.key
            return <Fragment key={r.key}><Table.Tr><Table.Td>{r.name}</Table.Td><Table.Td>{format(r.stock)}</Table.Td>
            <Table.Td><NumberInput aria-label={'Поступление ' + r.name} w={130} min={0} allowNegative={false} allowDecimal={false}
              value={receipts[r.key] || ''} placeholder="0" onChange={v => update(r.key, Number(v) || 0)} /></Table.Td>
            <Table.Td>{units(r.demand)}</Table.Td><Table.Td fw={700}>{format(order)}</Table.Td>
            <Table.Td>{units(last.balance)}</Table.Td><Table.Td>{last.coverage}</Table.Td>
            <Table.Td><Button size="compact-xs" variant="subtle" aria-expanded={open} onClick={() => setExpanded(open ? null : r.key)}>{open ? 'Свернуть' : 'Подробнее'}</Button></Table.Td></Table.Tr>
            {open && <Table.Tr><Table.Td colSpan={8}>
              <Text fw={600}>{r.name}</Text>
              <Text size="sm">Дефицит до округления = расход за период − доступный остаток − ожидаемое поступление: {format(Math.max(0, r.demand - r.stock - receipt))} шт. К заказу: {format(order)} шт.</Text>
              {r.products.map((p, index) => <Text key={index} size="sm">{p.name}: {format(p.sales)} изделий × {format(p.qty_per_1000)} / 1 000 = {units(p.demand)} шт.</Text>)}
              <Table stickyHeader={false}><Table.Thead><Table.Tr>{['Месяц', 'На начало', 'Поступление', 'Расход', 'На конец, шт.', 'Дней продаж'].map(h => <Table.Th key={h}>{h}</Table.Th>)}</Table.Tr></Table.Thead>
                <Table.Tbody>{periods.map(m => <Table.Tr key={m.date}><Table.Td>{month(m.date)}</Table.Td><Table.Td>{units(m.opening)}</Table.Td><Table.Td>{units(m.incoming)}</Table.Td><Table.Td>{units(m.demand)}</Table.Td><Table.Td c={m.balance < 0 ? 'red' : undefined}>{units(m.balance)}</Table.Td><Table.Td>{m.coverage}</Table.Td></Table.Tr>)}</Table.Tbody>
              </Table>
            </Table.Td></Table.Tr>}</Fragment>
          })}</Table.Tbody>
        </Table></Table.ScrollContainer>
      </Paper>
    })}
  </Stack>
}

export default function PrintOrderPage() {
  const [date, setDate] = useState(() => new Date().toLocaleDateString('sv-SE'))
  const [months, setMonths] = useState<string | number>(3)
  const [data, setData] = useState<Calculation>()
  const [error, setError] = useState('')
  const valid = !!date && typeof months === 'number' && Number.isInteger(months) && months >= 3 && months <= 24
  useEffect(() => {
    const controller = new AbortController()
    setData(undefined)
    setError('')
    if (valid) fetch('/api/planning/print-order?calc_date=' + date + '&months=' + months, { signal: controller.signal })
      .then(async res => {
        const result = await res.json()
        if (!res.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Ошибка расчёта')
        if (!controller.signal.aborted) setData(result)
      }).catch(e => { if (!controller.signal.aborted) setError(e.message) })
    return () => controller.abort()
  }, [date, months, valid])
  return <Stack><Title order={2}>Заказ в типографию</Title>
    <Group align="end"><TextInput label="Дата формирования" type="date" value={date} onChange={e => setDate(e.target.value)} />
      <NumberInput label="Месяцев продаж со следующего месяца" value={months} onChange={setMonths} min={3} max={24} allowDecimal={false} /></Group>
    {!valid ? <Text>Укажите дату и горизонт от 3 до 24 месяцев.</Text> : error ? <Alert color="red">{error}</Alert> : data ? <Order key={data.months[0]} data={data} /> : <Loader />}
  </Stack>
}
