import type { Category, PriceBand } from '@/api/dashboards'

export const CATEGORY_NAMES: Record<Category, string> = {
  apparel: 'Apparel',
  electronics_games: 'Electronics and games',
}

export const CATEGORIES: Category[] = ['apparel', 'electronics_games']

// Where a chart's or an answer's numbers come from: the synthetic history or the mock channels.
export type Source = 'history' | 'live'

// The bar down the left of a chart or an answer, a different color for each source.
export const SOURCE_LINE: Record<Source, string> = {
  history: 'border-plain-line',
  live: 'border-info-line',
}

// Each category's bar color on the dashboards.
export const SERIES_COLOR: Record<Category, string> = {
  apparel: 'bg-series-apparel',
  electronics_games: 'bg-series-games',
}

// Whole dollars without cents, so a band starts at "$15" and ends at "$29.99".
export function dollars(cents: number) {
  return cents % 100 === 0 ? `$${cents / 100}` : `$${(cents / 100).toFixed(2)}`
}

// A band runs from its low price up to but not including its high one.
export function bandName(band: PriceBand) {
  if (band.low_cents === null) return `Under ${dollars(band.high_cents ?? 0)}`
  if (band.high_cents === null) return `${dollars(band.low_cents)} and up`
  return `${dollars(band.low_cents)} to ${dollars(band.high_cents - 1)}`
}

export function count(value: number, one: string, many = `${one}s`) {
  return `${value.toLocaleString()} ${value === 1 ? one : many}`
}

export function share(part: number, whole: number) {
  return whole === 0 ? 0 : part / whole
}

export function percent(part: number, whole: number) {
  return `${Math.round(share(part, whole) * 100)}%`
}

// A demo sale often comes minutes after the listing went up, so a short time reads in minutes.
export function elapsed(hours: number) {
  if (hours * 60 < 1) return 'Under a minute'
  if (hours < 1) return count(Math.round(hours * 60), 'minute')
  if (hours < 48) return count(Math.round(hours * 10) / 10, 'hour')
  return count(Math.round((hours / 24) * 10) / 10, 'day')
}

export function monthName(month: number, style: 'long' | 'short' | 'narrow') {
  return new Date(2026, month - 1, 1).toLocaleString(undefined, { month: style })
}
