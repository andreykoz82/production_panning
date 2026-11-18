// Общие элементы интерфейса: заголовок страницы, карточка-показатель, блок с таблицей

import { Box, Card, Group, Paper, Stack, Text, ThemeIcon, Title, type MantineColor } from '@mantine/core'
import type { ReactNode } from 'react'

export function PageHeader({
  title,
  description,
  icon,
  actions,
}: {
  title: string
  description?: ReactNode
  icon?: ReactNode
  actions?: ReactNode
}) {
  return (
    <Group justify="space-between" align="flex-start" wrap="nowrap" mb="lg" gap="lg">
      <Group align="flex-start" wrap="nowrap" gap="md">
        {icon && (
          <ThemeIcon size={44} radius="md" variant="light">
            {icon}
          </ThemeIcon>
        )}
        <Box>
          <Title order={2} fz={24}>
            {title}
          </Title>
          {description && (
            <Text c="dimmed" size="sm" mt={4} maw={900}>
              {description}
            </Text>
          )}
        </Box>
      </Group>
      {actions && (
        <Group gap="xs" wrap="nowrap">
          {actions}
        </Group>
      )}
    </Group>
  )
}

export function StatCard({
  label,
  value,
  hint,
  icon,
  color = 'brand',
}: {
  label: string
  value: ReactNode
  hint?: ReactNode
  icon?: ReactNode
  color?: MantineColor
}) {
  return (
    <Card padding="md">
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <Stack gap={2}>
          <Text size="xs" c="dimmed" tt="uppercase" fw={600} lts={0.3}>
            {label}
          </Text>
          <Text fz={26} fw={700} lh={1.2}>
            {value}
          </Text>
          {hint && (
            <Text size="xs" c="dimmed">
              {hint}
            </Text>
          )}
        </Stack>
        {icon && (
          <ThemeIcon size={38} radius="md" variant="light" color={color}>
            {icon}
          </ThemeIcon>
        )}
      </Group>
    </Card>
  )
}

/** Белый блок с заголовком — для таблиц и списков */
export function Section({
  title,
  description,
  actions,
  children,
  p = 'md',
}: {
  title?: ReactNode
  description?: ReactNode
  actions?: ReactNode
  children: ReactNode
  p?: string | number
}) {
  return (
    <Paper withBorder shadow="xs" p={p}>
      {(title || actions) && (
        <Group justify="space-between" mb="sm" wrap="nowrap">
          <Box>
            {title && (
              <Text fw={650} size="md">
                {title}
              </Text>
            )}
            {description && (
              <Text size="xs" c="dimmed">
                {description}
              </Text>
            )}
          </Box>
          {actions && <Box style={{ flexShrink: 0 }}>{actions}</Box>}
        </Group>
      )}
      {children}
    </Paper>
  )
}
