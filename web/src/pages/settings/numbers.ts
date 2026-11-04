// Turning what a manager types into the API's numbers, and back. Each parser returns null for text that isn't a number of
// that kind, and the API checks the ranges.

export function dollars(cents: number) {
  return (cents / 100).toFixed(2)
}

export function parseDollars(text: string) {
  const match = /^\$?\s*(\d+)(?:\.(\d{1,2}))?$/.exec(text.trim())
  if (!match) return null
  return Number(match[1]) * 100 + Number((match[2] ?? '').padEnd(2, '0'))
}

// Rounded, so 0.136 shows as 13.6 and not 13.600000000000001.
export function percent(rate: number) {
  return String(Number((rate * 100).toFixed(4)))
}

export function parsePercent(text: string) {
  const match = /^(\d+(?:\.\d+)?)\s*%?$/.exec(text.trim())
  return match ? Number((Number(match[1]) / 100).toFixed(6)) : null
}

export function parseNumber(text: string) {
  const trimmed = text.trim()
  if (!/^\d*\.?\d+$/.test(trimmed)) return null
  return Number(trimmed)
}

export function parseWholeNumber(text: string) {
  const trimmed = text.trim().replaceAll(',', '')
  return /^\d+$/.test(trimmed) ? Number(trimmed) : null
}

// A comma-separated list, such as "4, 8, 12, 15.999", or null when any entry isn't a number.
export function parseNumberList(text: string) {
  const parts = text.split(',').map((part) => part.trim())
  const numbers = parts.map(parseNumber)
  return numbers.every((number) => number !== null) ? numbers : null
}

export function words(text: string) {
  return text
    .split(',')
    .map((word) => word.trim())
    .filter(Boolean)
}
