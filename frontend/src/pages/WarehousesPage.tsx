import { Alert, Badge, Button, Group, Select, Stack, Table, Text, Title } from '@mantine/core'
import { useCallback, useEffect, useState } from 'react'

import { warehouseApi, type WarehouseInfo } from '../api'

const num = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })

const ROLE_HINT: Record<string, string> = {
  gp_cert: 'запас ГП; продукция ждёт сертификации',
  gp_sale: 'запас ГП; продукция доступна к продаже',
  nfp: 'НФП для фасовки (с признаком «Фасовка = Да»)',
  nfp_quarantine: 'НФП станет доступен через 5 рабочих дней',
  byproducts: 'вторичные продукты для РПС и крупного порошка (1 ступень)',
  raw: 'сырьё для 1 ступени; покупной НФП (чай для Азерчая)',
  materials: 'упаковка для 2 ступени; строки «(отход)» не учитываются',
  ignore: 'в расчёте не участвует',
}

export default function WarehousesPage() {
  const [roles, setRoles] = useState<Record<string, string>>({})
  const [rows, setRows] = useState<WarehouseInfo[]>([])
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    warehouseApi
      .list()
      .then((d) => {
        setRoles(d.roles)
        setRows(d.warehouses)
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  useEffect(load, [load])

  const save = (warehouse: string, role: string | null) => {
    setError(null)
    warehouseApi.setRole(warehouse, role).then(load).catch((e: Error) => setError(e.message))
  }

  return (
    <Stack>
      <div>
        <Title order={3}>Склады</Title>
        <Text c="dimmed" size="sm">
          Как каждый склад из отчёта «Остатки по складам» участвует в расчёте. Новый склад по умолчанию не учитывается —
          назначьте ему роль. Изменения применяются к следующему расчёту потребности; Гант перепланируется сразу.
        </Text>
      </div>
      {error && <Alert color="red">{error}</Alert>}
      <Table striped highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Склад</Table.Th>
            <Table.Th w={320}>Роль в расчёте</Table.Th>
            <Table.Th>Что это значит</Table.Th>
            <Table.Th ta="right">Строк</Table.Th>
            <Table.Th ta="right">Доступно</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((w) => (
            <Table.Tr key={w.warehouse} opacity={w.in_snapshot ? 1 : 0.5}>
              <Table.Td>
                <Text size="sm" fw={500}>
                  {w.warehouse}
                </Text>
                <Group gap={4}>
                  {!w.known && (
                    <Badge size="xs" color="orange" variant="light">
                      новый склад
                    </Badge>
                  )}
                  {!w.in_snapshot && (
                    <Badge size="xs" color="gray" variant="light">
                      нет в последней выгрузке
                    </Badge>
                  )}
                </Group>
              </Table.Td>
              <Table.Td>
                <Group gap={6} wrap="nowrap">
                  <Select
                    size="xs"
                    w={250}
                    allowDeselect={false}
                    value={w.role}
                    data={Object.entries(roles).map(([value, label]) => ({ value, label }))}
                    onChange={(v) => v && v !== w.role && save(w.warehouse, v)}
                  />
                  {w.manual && (
                    <Button size="compact-xs" variant="subtle" onClick={() => save(w.warehouse, null)}>
                      по умолчанию
                    </Button>
                  )}
                </Group>
              </Table.Td>
              <Table.Td>
                <Text size="xs" c={w.role === 'ignore' ? 'dimmed' : undefined}>
                  {ROLE_HINT[w.role]}
                </Text>
              </Table.Td>
              <Table.Td ta="right">{w.rows}</Table.Td>
              <Table.Td ta="right">{num.format(w.available)}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  )
}
