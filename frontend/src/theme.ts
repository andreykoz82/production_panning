import { Badge, Card, NavLink, Paper, Table, Tabs, createTheme, type MantineColorsTuple } from '@mantine/core'

// Фирменный зелёный — «травяной», спокойный, хорошо читается на светлом фоне
const brand: MantineColorsTuple = [
  '#e9fbf2',
  '#d6f2e4',
  '#aee3c8',
  '#83d4aa',
  '#5ec791',
  '#46bf81',
  '#37bb78',
  '#27a466',
  '#1c925a',
  '#027d4b',
]

export const theme = createTheme({
  primaryColor: 'brand',
  primaryShade: 7,
  colors: { brand },
  defaultRadius: 'md',
  fontFamily: "'Inter Variable', 'Segoe UI', system-ui, sans-serif",
  headings: { fontFamily: "'Inter Variable', 'Segoe UI', system-ui, sans-serif", fontWeight: '650' },
  shadows: {
    xs: '0 1px 2px rgba(16, 24, 40, 0.05)',
    sm: '0 1px 3px rgba(16, 24, 40, 0.08), 0 1px 2px rgba(16, 24, 40, 0.04)',
  },
  components: {
    Card: Card.extend({ defaultProps: { withBorder: true, shadow: 'xs', radius: 'lg' } }),
    Paper: Paper.extend({ defaultProps: { radius: 'lg' } }),
    Table: Table.extend({
      defaultProps: { highlightOnHover: true, verticalSpacing: 8, horizontalSpacing: 'sm' },
      styles: {
        th: { fontSize: 12, fontWeight: 600, color: 'var(--mantine-color-gray-7)', whiteSpace: 'nowrap' },
      },
    }),
    Badge: Badge.extend({ defaultProps: { variant: 'light', radius: 'sm' } }),
    Tabs: Tabs.extend({ defaultProps: { variant: 'pills', radius: 'md' } }),
    NavLink: NavLink.extend({
      styles: { root: { borderRadius: 8 }, label: { fontWeight: 500 } },
    }),
  },
})
