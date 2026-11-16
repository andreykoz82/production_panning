export type Severity = 'error' | 'warning' | 'info'

export interface Snapshot {
  id: number
  created_at: string
  source: string
  files: Record<string, string>
  summary: {
    items_total: number
    items_in_scope: number
    items_with_spec: number
    items_spec_to_confirm: number
    stock_rows: number
    specs_total: number
    specs_multi_version: number
    plan_rows: number
    plan_from: string | null
    plan_to: string | null
    orders_stage2: number
    issues: Record<Severity, number>
  }
}

export interface Issue {
  severity: Severity
  area: string
  item: string | null
  message: string
}

export interface Item {
  name: string
  abc: string
  line_group: string | null
  form: string | null
  nfp: string | null
  nfp_source: string | null
  in_scope: boolean
  spec: string | null
  spec_method: string | null
  spec_score: number
  spec_needs_confirmation: boolean
}

export interface Line {
  code: string
  stage: number
  group: string
  capacity: number
  unit: string
  per_hour: number
  min_batch: number | null
  setters: number
  workers: number
  note: string
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail ?? `Ошибка ${res.status}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  snapshots: () => request<Snapshot[]>('/api/imports'),
  importFromFolder: () => request<Snapshot>('/api/imports/from-folder', { method: 'POST' }),
  importUpload: (files: File[]) => {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    return request<Snapshot>('/api/imports/upload', { method: 'POST', body: form })
  },
  issues: (id: number) => request<Issue[]>(`/api/imports/${id}/issues`),
  items: (id: number) => request<Item[]>(`/api/imports/${id}/items`),
  lines: () => request<Line[]>('/api/reference/lines'),
}
