type Material = { name: string; key: string }
const normalize = (name: string) => name.trim().replace(/\s+/g, ' ').toLocaleLowerCase('ru')
const columns = ['Материал', 'Количество']

export async function saveTemplate(materials: Material[], month: string) {
  const { default: Excel } = await import('exceljs')
  const book = new Excel.Workbook()
  const sheet = book.addWorksheet(month)
  sheet.addRow(columns)
  for (const material of materials) sheet.addRow([material.name])
  sheet.getColumn(1).width = 80
  sheet.getColumn(2).width = 18
  sheet.getRow(1).font = { bold: true }
  const buffer = await book.xlsx.writeBuffer()
  const url = URL.createObjectURL(new Blob([new Uint8Array(buffer)]))
  const link = document.createElement('a')
  link.href = url
  link.download = 'Поступления ' + month + '.xlsx'
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export async function readReceipts(file: File, materials: Material[], month: string) {
  const { default: Excel } = await import('exceljs')
  const book = new Excel.Workbook()
  await book.xlsx.load(await file.arrayBuffer())
  const sheet = book.worksheets[0]
  if (!sheet) throw new Error('В файле нет листов')
  if (/^\d{4}-\d{2}$/.test(sheet.name) && sheet.name !== month)
    throw new Error('Шаблон заполнен для другого месяца: ' + sheet.name)
  const headers = new Map<string, number>()
  sheet.getRow(1).eachCell((cell, index) => headers.set(normalize(cell.text), index))
  const nameCol = headers.get('материал'), qtyCol = headers.get('количество')
  if (!nameCol || !qtyCol) throw new Error('На первом листе нужны заголовки «Материал» и «Количество»')
  const lookup = new Map(materials.map(r => [normalize(r.name), r.key]))
  const amounts: Record<string, number> = {}
  sheet.eachRow((row, index) => {
    if (index === 1) return
    const raw = row.getCell(qtyCol).text.trim()
    if (!raw) return
    const name = row.getCell(nameCol).text
    const key = lookup.get(normalize(name))
    if (!key) throw new Error('Строка ' + index + ': неизвестный материал «' + name + '»')
    const digits = raw.replace(/[ \u00a0\u202f]/g, '')
    const total = (amounts[key] || 0) + Number(digits)
    if (!/^\d+$/.test(digits) || !Number.isSafeInteger(total))
      throw new Error('Строка ' + index + ': количество должно быть целым числом от нуля')
    amounts[key] = total
  })
  if (!Object.keys(amounts).length) throw new Error('В файле нет заполненных количеств')
  return amounts
}
