import { AppShell, Group, Loader, NavLink, Text, Title } from '@mantine/core'
import { lazy, Suspense, useState } from 'react'

import CalendarsPage from './pages/CalendarsPage'
import ImportPage from './pages/ImportPage'
import LinesPage from './pages/LinesPage'
import Stage2Page from './pages/Stage2Page'
import WarehousesPage from './pages/WarehousesPage'

// Гант тянет vis-timeline — грузим только при открытии
const GanttPage = lazy(() => import('./pages/GanttPage'))

const PAGES = [
  { key: 'import', label: 'Импорт данных 1С', element: <ImportPage /> },
  { key: 'stage2', label: 'Потребность 2 ступени', element: <Stage2Page /> },
  { key: 'gantt', label: 'Гант 2 ступени', element: <GanttPage /> },
  { key: 'calendars', label: 'Календари линий', element: <CalendarsPage /> },
  { key: 'warehouses', label: 'Склады', element: <WarehousesPage /> },
  { key: 'lines', label: 'Линии и мощности', element: <LinesPage /> },
] as const

// Следующие этапы
const PLANNED = ['Потребность 1 ступени', 'Гант 1 ступени']

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
      <AppShell.Main>
        <Suspense fallback={<Loader />}>{current.element}</Suspense>
      </AppShell.Main>
    </AppShell>
  )
}
