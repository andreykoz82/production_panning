import {
  Alert,
  Badge,
  Button,
  Card,
  FileButton,
  Group,
  Select,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Table,
  Tabs,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { api, type Issue, type Item, type Severity, type Snapshot } from '../api'

const SEVERITY: Record<Severity, { label: string; color: string }> = {
  error: { label: 'Ошибка', color: 'red' },
  warning: { label: 'Внимание', color: 'orange' },
  info: { label: 'Инфо', color: 'gray' },
}

const AREA: Record<string, string> = {
  items: 'Справочник ГП',
  specs: 'Спецификации',
  stock: 'Остатки',
  plan: 'План продаж',
  orders: 'Заказы',
}

const METHOD: Record<string, { label: string; color: string }> = {
  exact: { label: 'точно', color: 'teal' },
  normalized: { label: 'иное написание', color: 'blue' },
  printed_material: { label: 'по печатному материалу', color: 'indigo' },
  fuzzy: { label: 'похожее имя — проверить', color: 'orange' },
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

export default function ImportPage() {
  const [snapshots, setSnapshots] = useState<Snapshot[]>([])
  const [selected, setSelected] = useState<number | null>(null)
  const [issues, setIssues] = useState<Issue[]>([])
  const [items, setItems] = useState<Item[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [severity, setSeverity] = useState<'all' | Severity>('all')
  const [search, setSearch] = useState('')

  const loadSnapshots = useCallback(async (select?: number) => {
    const list = await api.snapshots()
    setSnapshots(list)
    setSelected(select ?? list[0]?.id ?? null)
  }, [])

  useEffect(() => {
    loadSnapshots().catch((e: Error) => setError(e.message))
  }, [loadSnapshots])

  useEffect(() => {
    if (selected == null) return
    Promise.all([api.issues(selected), api.items(selected)])
      .then(([i, it]) => {
        setIssues(i)
        setItems(it)
      })
      .catch((e: Error) => setError(e.message))
  }, [selected])

  const run = async (action: () => Promise<Snapshot>) => {
    setBusy(true)
    setError(null)
    try {
      const snap = await action()
      await loadSnapshots(snap.id)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const snap = snapshots.find((s) => s.id === selected)
  const shownIssues = useMemo(() => {
    const q = search.trim().toLowerCase()
    return issues.filter(
      (i) =>
        (severity === 'all' || i.severity === severity) &&
        (!q || `${i.item ?? ''} ${i.message}`.toLowerCase().includes(q)),
    )
  }, [issues, severity, search])
  const shownItems = useMemo(() => {
    const q = search.trim().toLowerCase()
    return items.filter((i) => !q || `${i.name} ${i.spec ?? ''}`.toLowerCase().includes(q))
  }, [items, search])

  return (
    <Stack>
      <Group justify="space-between" align="flex-end">
        <div>
          <Title order={3}>Импорт данных из 1С</Title>
          <Text c="dimmed" size="sm">
            actual_items, остатки по складам, ресурсные спецификации, планы продаж, открытые заказы 2 ступени
          </Text>
        </div>
        <Group>
          <Button loading={busy} onClick={() => run(api.importFromFolder)}>
            Загрузить из папки «Исходные данные»
          </Button>
          <FileButton multiple accept=".xlsx,.xls" onChange={(files) => files.length && run(() => api.importUpload(files))}>
            {(props) => (
              <Button variant="light" loading={busy} {...props}>
                Выбрать файлы…
              </Button>
            )}
          </FileButton>
        </Group>
      </Group>

      {error && (
        <Alert color="red" title="Не удалось загрузить">
          {error}
        </Alert>
      )}

      {snapshots.length > 0 && (
        <Select
          label="Снимок данных"
          w={360}
          value={selected?.toString() ?? null}
          onChange={(v) => setSelected(v ? Number(v) : null)}
          data={snapshots.map((s) => ({
            value: s.id.toString(),
            label: `#${s.id} от ${new Date(s.created_at).toLocaleString('ru-RU')} (${s.source === 'folder' ? 'папка' : 'файлы'})`,
          }))}
        />
      )}

      {!snap && !error && <Text c="dimmed">Данных ещё нет — загрузите выгрузки из 1С.</Text>}

      {snap && (
        <>
          <SimpleGrid cols={{ base: 2, md: 4 }}>
            <Stat
              label="ГП в планировании"
              value={`${snap.summary.items_in_scope} из ${snap.summary.items_total}`}
              hint="без розлива и контрактной площадки"
            />
            <Stat
              label="Со спецификацией"
              value={snap.summary.items_with_spec}
              hint={`проверить связь: ${snap.summary.items_spec_to_confirm}`}
            />
            <Stat
              label="План продаж"
              value={`${snap.summary.plan_from?.slice(0, 7)} … ${snap.summary.plan_to?.slice(0, 7)}`}
              hint={`${snap.summary.plan_rows} строк`}
            />
            <Stat label="Открытых заказов 2 ступени" value={snap.summary.orders_stage2} />
          </SimpleGrid>

          <TextInput
            placeholder="Поиск по наименованию или тексту"
            value={search}
            onChange={(e) => setSearch(e.currentTarget.value)}
            w={420}
          />

          <Tabs defaultValue="issues">
            <Tabs.List>
              <Tabs.Tab value="issues">
                Проблемы в данных ({snap.summary.issues.error} / {snap.summary.issues.warning} /{' '}
                {snap.summary.issues.info})
              </Tabs.Tab>
              <Tabs.Tab value="items">ГП и спецификации ({items.length})</Tabs.Tab>
            </Tabs.List>

            <Tabs.Panel value="issues" pt="md">
              <SegmentedControl
                mb="sm"
                value={severity}
                onChange={(v) => setSeverity(v as 'all' | Severity)}
                data={[
                  { value: 'all', label: 'Все' },
                  { value: 'error', label: `Ошибки (${snap.summary.issues.error})` },
                  { value: 'warning', label: `Внимание (${snap.summary.issues.warning})` },
                  { value: 'info', label: `Инфо (${snap.summary.issues.info})` },
                ]}
              />
              <Table striped>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th w={110}>Уровень</Table.Th>
                    <Table.Th w={150}>Раздел</Table.Th>
                    <Table.Th>Позиция</Table.Th>
                    <Table.Th>Что не так</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {shownIssues.map((i, idx) => (
                    <Table.Tr key={idx}>
                      <Table.Td>
                        <Badge color={SEVERITY[i.severity].color} variant="light">
                          {SEVERITY[i.severity].label}
                        </Badge>
                      </Table.Td>
                      <Table.Td>{AREA[i.area] ?? i.area}</Table.Td>
                      <Table.Td>{i.item ?? '—'}</Table.Td>
                      <Table.Td>{i.message}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Tabs.Panel>

            <Tabs.Panel value="items" pt="md">
              <Table striped>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>ГП</Table.Th>
                    <Table.Th w={50}>ABC</Table.Th>
                    <Table.Th>Группа линий</Table.Th>
                    <Table.Th>НФП</Table.Th>
                    <Table.Th>Спецификация</Table.Th>
                    <Table.Th>Как найдена</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {shownItems.map((i) => (
                    <Table.Tr key={i.name} opacity={i.in_scope ? 1 : 0.5}>
                      <Table.Td>{i.name}</Table.Td>
                      <Table.Td>{i.abc}</Table.Td>
                      <Table.Td>{i.line_group}</Table.Td>
                      <Table.Td>{i.nfp ?? <Text c="red">нет</Text>}</Table.Td>
                      <Table.Td>{i.spec ?? (i.in_scope ? <Text c="red">не найдена</Text> : '—')}</Table.Td>
                      <Table.Td>
                        {i.spec_method ? (
                          <Badge variant="light" color={METHOD[i.spec_method]?.color}>
                            {METHOD[i.spec_method]?.label ?? i.spec_method}
                          </Badge>
                        ) : (
                          !i.in_scope && <Text size="sm">не планируется</Text>
                        )}
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
