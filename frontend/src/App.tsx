import { AppShell, Badge, Box, Burger, Group, Loader, NavLink, Stack, Text, ThemeIcon } from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import {
  IconBuildingWarehouse,
  IconCalendarTime,
  IconChartBar,
  IconClipboardList,
  IconCloudDownload,
  IconHourglass,
  IconLayoutKanban,
  IconLeaf,
  IconSettingsCog,
  IconTimeline,
} from '@tabler/icons-react'
import { lazy, Suspense, useState, type ReactNode } from 'react'

import CalendarsPage from './pages/CalendarsPage'
import ImportPage from './pages/ImportPage'
import LinesPage from './pages/LinesPage'
import PrintOrderPage from './pages/PrintOrderPage'
import Stage2Page from './pages/Stage2Page'
import WarehousesPage from './pages/WarehousesPage'

// Гант тянет vis-timeline, сроки годности — графики: грузим только при открытии
const GanttPage = lazy(() => import('./pages/GanttPage'))
const ShelfLifePage = lazy(() => import('./pages/ShelfLifePage'))

type Page = { key: string; label: string; icon: ReactNode; element?: ReactNode; soon?: boolean }

const SECTIONS: { title: string; pages: Page[] }[] = [
  {
    title: 'Данные',
    pages: [{ key: 'import', label: 'Импорт из 1С', icon: <IconCloudDownload size={18} />, element: <ImportPage /> }],
  },
  {
    title: '2 ступень · фасовка',
    pages: [
      { key: 'stage2', label: 'Потребность', icon: <IconClipboardList size={18} />, element: <Stage2Page /> },
      { key: 'printing', label: 'Заказ в типографию', icon: <IconClipboardList size={18} />, element: <PrintOrderPage /> },
      { key: 'gantt', label: 'График производства', icon: <IconTimeline size={18} />, element: <GanttPage /> },
      { key: 'shelf', label: 'Сроки годности ГП', icon: <IconHourglass size={18} />, element: <ShelfLifePage /> },
    ],
  },
  {
    title: '1 ступень · переработка',
    pages: [
      { key: 'stage1', label: 'Потребность', icon: <IconChartBar size={18} />, soon: true },
      { key: 'gantt1', label: 'График производства', icon: <IconLayoutKanban size={18} />, soon: true },
    ],
  },
  {
    title: 'Настройки',
    pages: [
      { key: 'calendars', label: 'Календари линий', icon: <IconCalendarTime size={18} />, element: <CalendarsPage /> },
      { key: 'warehouses', label: 'Склады', icon: <IconBuildingWarehouse size={18} />, element: <WarehousesPage /> },
      { key: 'lines', label: 'Линии и мощности', icon: <IconSettingsCog size={18} />, element: <LinesPage /> },
    ],
  },
]

const PAGES = SECTIONS.flatMap((s) => s.pages).filter((p) => p.element)

export default function App() {
  const [page, setPage] = useState<string>('import')
  const [opened, { toggle, close }] = useDisclosure()
  const current = PAGES.find((p) => p.key === page) ?? PAGES[0]

  return (
    <AppShell
      header={{ height: 60 }}
      navbar={{ width: 260, breakpoint: 'sm', collapsed: { mobile: !opened } }}
      padding="lg"
      styles={{ main: { background: 'var(--mantine-color-gray-0)' } }}
    >
      <AppShell.Header>
        <Group h="100%" px="lg" justify="space-between">
          <Group gap="sm">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <ThemeIcon size={34} radius="md" variant="gradient" gradient={{ from: 'brand.6', to: 'teal.7', deg: 135 }}>
              <IconLeaf size={20} />
            </ThemeIcon>
            <Box>
              <Text fw={700} lh={1.1}>
                Планирование производства
              </Text>
              <Text size="xs" c="dimmed" lh={1.2}>
                АО «Красногорсклексредства»
              </Text>
            </Box>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="sm">
        <Stack gap="md">
          {SECTIONS.map((section) => (
            <Box key={section.title}>
              <Text size="xs" fw={600} c="dimmed" tt="uppercase" lts={0.4} px="sm" mb={4}>
                {section.title}
              </Text>
              {section.pages.map((p) => (
                <NavLink
                  key={p.key}
                  label={p.label}
                  leftSection={p.icon}
                  active={p.key === page}
                  disabled={p.soon}
                  rightSection={
                    p.soon ? (
                      <Badge size="xs" color="gray">
                        скоро
                      </Badge>
                    ) : undefined
                  }
                  onClick={() => {
                    setPage(p.key)
                    close()
                  }}
                />
              ))}
            </Box>
          ))}
        </Stack>
      </AppShell.Navbar>

      <AppShell.Main>
        <Box maw={1800} mx="auto">
          <Suspense fallback={<Loader m="xl" />}>{current.element}</Suspense>
        </Box>
      </AppShell.Main>
    </AppShell>
  )
}
