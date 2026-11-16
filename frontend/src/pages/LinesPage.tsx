import { Alert, Badge, Stack, Table, Text, Title } from '@mantine/core'
import { useEffect, useState } from 'react'

import { api, type Line } from '../api'

const fmt = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })

export default function LinesPage() {
  const [lines, setLines] = useState<Line[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.lines().then(setLines).catch((e: Error) => setError(e.message))
  }, [])

  return (
    <Stack>
      <Title order={3}>Линии и мощности</Title>
      <Text c="dimmed" size="sm">
        2 ступень: норма в шт. за смену 8 ч, переналадка 1 ч, минимальная партия — выпуск за 1 ч. 1 ступень:
        кг/ч, переналадка 5 ч. Заказ можно ставить на любую линию своей группы.
      </Text>
      {error && <Alert color="red">{error}</Alert>}
      <Table striped highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Ступень</Table.Th>
            <Table.Th>Линия</Table.Th>
            <Table.Th>Группа</Table.Th>
            <Table.Th ta="right">Норма</Table.Th>
            <Table.Th ta="right">В час</Table.Th>
            <Table.Th ta="right">Мин. партия</Table.Th>
            <Table.Th ta="right">Наладчики / рабочие</Table.Th>
            <Table.Th>Назначение</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {lines.map((l) => (
            <Table.Tr key={l.code}>
              <Table.Td>
                <Badge variant="light" color={l.stage === 1 ? 'grape' : 'teal'}>
                  {l.stage}
                </Badge>
              </Table.Td>
              <Table.Td fw={600}>{l.code}</Table.Td>
              <Table.Td>{l.group}</Table.Td>
              <Table.Td ta="right">
                {fmt.format(l.capacity)} {l.unit}
              </Table.Td>
              <Table.Td ta="right">{fmt.format(l.per_hour)}</Table.Td>
              <Table.Td ta="right">{l.min_batch == null ? '—' : `${fmt.format(l.min_batch)} шт.`}</Table.Td>
              <Table.Td ta="right">
                {l.setters} / {l.workers}
              </Table.Td>
              <Table.Td>{l.note}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  )
}
