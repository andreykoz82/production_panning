import '@fontsource-variable/inter'
import '@mantine/core/styles.css'
import '@mantine/charts/styles.css'

import { MantineProvider } from '@mantine/core'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import App from './App.tsx'
import { theme } from './theme'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MantineProvider theme={theme}>
      <App />
    </MantineProvider>
  </StrictMode>,
)
