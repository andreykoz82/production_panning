export type Severity = 'error' | 'warning' | 'info'

export interface Snapshot {
  id: number
  created_at: string
  source: string
  files: Record<string, string>
  summary: {
    items_total: number
    items_in_scope: number
    items_stm?: number
    items_with_spec: number
    items_spec_to_confirm: number
    stock_rows: number
    specs_total: number
    specs_with_products?: number
    items_spec_by_product?: number
    specs_multi_version: number
    plan_rows: number
    plan_from: string | null
    plan_to: string | null
    orders_stage1?: number
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
  kind?: string | null
  min_series?: number | null
  max_series?: number | null
  stm?: boolean
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

export type Stage2Status = 'Не требуется' | 'Можно фасовать' | 'Частично' | 'Нельзя' | 'Нет данных'

export interface Stage2Line {
  priority: number
  item: string
  stm?: boolean
  abc: string
  line_group: string | null
  nfp: string | null
  plan_horizon: number
  gp_stock: number
  gp_on_certification: number
  open_orders: number
  need: number
  min_batch: number
  min_series?: number | null
  max_series?: number | null
  series?: number
  series_size?: number
  stockout_month: string | null
  feasible: number
  limit: string | null
  status: Stage2Status
  nfp_characteristic: string | null
  nfp_need_kg: number
  nfp_available_kg: number
  nfp_quarantine_kg: number
  nfp_unreleased_kg: number
  nfp_shortage_kg: number
}

export interface MaterialLine {
  material: string
  kind?: string | null
  need: number
  available: number
  shortage: number
  items: number
  item_names: string
  deviation_pct?: number
  within_tolerance?: boolean
}

export interface NfpLine {
  nfp: string
  characteristic: string | null
  purpose: string | null
  need_kg: number
  available_kg: number
  quarantine_kg: number
  quarantine_ready: string | null
  unreleased_kg: number
  shortage_kg: number
  stage1_orders_kg?: number
  uncovered_kg?: number
  items: string
}

export interface PlanRun {
  id: number
  snapshot_id: number
  created_at: string
  stage: number
  params: { horizon_months: number; calc_date: string }
  summary: {
    items: number
    items_needed: number
    items_full: number
    items_partial: number
    items_blocked: number
    need_units: number
    feasible_units: number
    materials_short: number
    nfp_shortage_kg: number
    nfp_stage1_orders_kg?: number
    nfp_uncovered_kg?: number
    stm_items?: number
    stm_needed?: number
    stm_need_units?: number
    stm_feasible_units?: number
    month_factors: Record<string, number>
    warehouses?: Record<string, string[]>
  }
}

export interface PlanRunDetail extends PlanRun {
  lines: Stage2Line[]
  materials: MaterialLine[]
  nfp: NfpLine[]
}

export const planningApi = {
  runs: () => request<PlanRun[]>('/api/planning/runs'),
  run: (id: number) => request<PlanRunDetail>(`/api/planning/runs/${id}`),
  calculate: (horizon_months: number, calc_date: string) =>
    request<PlanRunDetail>('/api/planning/stage2', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ horizon_months, calc_date }),
    }),
  exportUrl: (id: number) => `/api/planning/runs/${id}/export`,
}

// ---------- календари и Гант

export interface CalendarDay {
  day: string
  shifts: number
  template: number
  manual: boolean
  reason: string | null
}

export interface CalendarLine {
  title?: string
  line_code: string
  stage: number
  group: string
  mode: '5/2' | '24/7'
  template_shifts: number
  days: CalendarDay[]
  hours: number
}

export interface CalendarMonth {
  month: string
  days: { day: string; workday: boolean }[]
  lines: CalendarLine[]
}

export interface ScheduleTask {
  id: number
  number: string
  item: string
  qty: number
  line_group: string | null
  line_code: string | null
  start: string | null
  end: string | null
  hours: number
  changeover: boolean
  line_locked: boolean
  line_source: '1c' | 'manual' | 'auto' | null
  line_1c_code: string | null
  seq: number | null
  stockout_month: string | null
  stm: boolean
  available_from: string | null
  warnings: string[]
  status: string | null
  line_1c: string | null
  started_at: string | null
  qty_plan: number | null
  qty_done: number | null
}

export interface Schedule {
  lines: { code: string; title?: string; group: string; per_hour: number }[]
  tasks: ScheduleTask[]
  off: { line_code: string; start: string; end: string }[]
}

export interface CapacityGroup {
  group: string
  stage: number
  unit: string
  lines: string[]
  months: { month: string; hours: number; output: number }[]
  total_hours: number
  total: number
  need: number | null
  open_orders: number | null
}

export interface Capacity {
  months: string[]
  from: string
  horizon_months: number | null
  groups: CapacityGroup[]
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const scheduleApi = {
  month: (month: string) => request<CalendarMonth>(`/api/calendars?month=${month}`),
  setTemplate: (line_code: string, mode: string, shifts: number) =>
    request('/api/calendars/template', json('PUT', { line_code, mode, shifts })),
  setDays: (changes: { line_code: string; day: string; shifts: number | null; reason?: string }[]) =>
    request('/api/calendars/days', json('PUT', { changes })),
  resetMonth: (month: string, line_code?: string) =>
    request(`/api/calendars/month?month=${month}${line_code ? `&line_code=${encodeURIComponent(line_code)}` : ''}`, {
      method: 'DELETE',
    }),
  schedule: (from: string, to: string) => request<Schedule>(`/api/schedule?from=${from}&to=${to}`),
  sync: () =>
    request<{ added: number; updated: number; removed: number; total: number }>('/api/schedule/sync', {
      method: 'POST',
    }),
  replan: () => request('/api/schedule/replan', { method: 'POST' }),
  patchTask: (id: number, patch: { line_code?: string; pin_line?: boolean; from_1c?: boolean }) =>
    request(`/api/schedule/tasks/${id}`, json('PATCH', patch)),
  setQueues: (queues: Record<string, number[]>) => request('/api/schedule/queues', json('PUT', { queues })),
  resetQueue: (line_code: string) =>
    request(`/api/schedule/queues/${encodeURIComponent(line_code)}`, { method: 'DELETE' }),
  capacity: (month: string, months = 3) => request<Capacity>(`/api/calendars/capacity?month=${month}&months=${months}`),
}

export interface WarehouseInfo {
  warehouse: string
  role: string
  default_role: string
  manual: boolean
  known: boolean
  rows: number
  available: number
  in_snapshot: boolean
}

export const warehouseApi = {
  list: () => request<{ roles: Record<string, string>; warehouses: WarehouseInfo[] }>('/api/warehouses'),
  setRole: (warehouse: string, role: string | null) => request('/api/warehouses', json('PUT', { warehouse, role })),
}

// ---------- сроки годности ГП

export type ShelfStatus = 'Неликвид есть' | 'Уйдёт в неликвид' | 'Не хватит' | 'Норма'

export interface ShelfParams {
  horizon_months: number
  fulfillment_pct: number
  threshold_pct: number
  replenish: boolean
  cover_months: number
  bottling: boolean
}

export interface ShelfItem {
  item: string
  bottling: boolean
  status: ShelfStatus
  shelf_life_months: number | null
  stock: number
  lots: number
  illiquid_now: number
  illiquid_forecast: number
  illiquid_total: number
  first_illiquid: string | null
  monthly_demand: number
  coverage_months: number | null
  sales: number
  demand: number
  lost_sales: number
  produced_orders: number
  produced_planned: number
}

export interface ShelfMonth {
  month: string
  sales: number
  demand: number
  orders: number
  planned: number
  illiquid: number
  lost: number
  liquid_end: number
  illiquid_end: number
}

export interface ShelfLot {
  series: string
  source: 'склад' | 'заказ' | 'наработка'
  qty: number
  production: string
  available: string
  expiry: string
  illiquid_from: string
  residual_pct: number
  sold: number
  sold_out: string | null
  illiquid_qty: number
  illiquid_date: string | null
  left: number
}

export interface ShelfAnalysis {
  params: ShelfParams & { calc_date: string }
  report_date: string | null
  summary: {
    items: number
    lots: number
    lots_out_of_scope: number
    items_bottling: number
    stock: number
    illiquid_now: number
    illiquid_forecast: number
    items_illiquid_now: number
    items_at_risk: number
    sales: number
    demand: number
    lost_sales: number
    produced_orders: number
    produced_planned: number
  }
  months: ShelfMonth[]
  items: ShelfItem[]
  detail: {
    item: string
    row: ShelfItem
    points: { date: string; liquid: number; illiquid: number; arrived: number; sold: number; lost: number }[]
    months: ShelfMonth[]
    lots: ShelfLot[]
  } | null
}

export const shelfApi = {
  analyze: (p: ShelfParams, item?: string) => {
    const q = new URLSearchParams(Object.entries({ ...p, ...(item ? { item } : {}) }).map(([k, v]) => [k, String(v)]))
    return request<ShelfAnalysis>(`/api/shelf-life?${q}`)
  },
}
