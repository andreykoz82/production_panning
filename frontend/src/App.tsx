import { AppShell, Group, NavLink, Text, Title } from '@mantine/core'
import { useState } from 'react'

import ImportPage from './pages/ImportPage'
import LinesPage from './pages/LinesPage'

const PAGES = [
  { key: 'import', label: 'Импорт данных 1С', element: <ImportPage /> },
  { key: 'lines', label: 'Линии и мощности', element: <LinesPage /> },
] as const

// Следующие этапы: потребность 2 ступени, календари линий, Гант, 1 ступень
const PLANNED = ['Потребность 2 ступени', 'Календари линий', 'Гант 2 ступени', '1 ступень']

export default function App() {
  const [page, setPage] = useState<string>('import')
  const current = PAGES.find((p) => p.key === page) ?? PAGES[0]

  return (
    <AppShell header={{ height: 56 }} navbar={{ width: 240, breakpoint: 'sm' }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md">
          <Title order={4}>Планирование производства</Title>
          <Text c="dimmed" size="sm">
            АО «Красногорсклексредства»
          </Text>
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="xs">
        {PAGES.map((p) => (
          <NavLink key={p.key} label={p.label} active={p.key === page} onClick={() => setPage(p.key)} />
        ))}
        {PLANNED.map((label) => (
          <NavLink key={label} label={label} disabled description="следующий этап" />
        ))}
      </AppShell.Navbar>
      <AppShell.Main>{current.element}</AppShell.Main>
    </AppShell>
  )
}
