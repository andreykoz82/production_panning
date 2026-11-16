import '@mantine/core/styles.css'

import { MantineProvider, createTheme } from '@mantine/core'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import App from './App.tsx'

const theme = createTheme({ primaryColor: 'teal', defaultRadius: 'md' })

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MantineProvider theme={theme}>
      <App />
    </MantineProvider>
  </StrictMode>,
)
