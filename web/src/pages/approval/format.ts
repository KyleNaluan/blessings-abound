import type { Channel, ItemStatus } from '@/api/approval'

export const CHANNEL_NAMES: Record<Channel, string> = {
  channel_a: 'Channel A',
  channel_b: 'Channel B',
}

// Cents as dollars, with the minus sign before the dollar sign for a sale that loses money.
export function money(cents: number) {
  const amount = `$${(Math.abs(cents) / 100).toFixed(2)}`
  return cents < 0 ? `-${amount}` : amount
}

// A billed weight is an ounce tier under a pound and whole pounds from there.
export function billedWeight(oz: number) {
  return oz < 16 ? `${oz} oz` : `${oz / 16} lb`
}

// A code with two sizes is a flat mailer, and one with three is a box, as Settings names them.
export function boxLabel(code: string) {
  return code.split('x').length === 2 ? `${code} mailer` : `${code} box`
}

export function when(iso: string) {
  return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

// To the second, for times that are often a minute or less apart, such as two orders.
export function exactly(iso: string) {
  return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'medium' })
}

// A release month is the first day of the month, as a date with no time.
export function releaseMonth(isoDate: string) {
  const [year, month] = isoDate.split('-').map(Number)
  return new Date(year, month - 1, 1).toLocaleString(undefined, { month: 'long', year: 'numeric' })
}

export const STATUS_NAMES: Partial<Record<ItemStatus, string>> = {
  appraised: 'Waiting for approval',
  approved: 'Approved',
  held_for_season: 'Approved and held for its season',
  declined: 'Rejected',
  not_listed_online: 'Not listed online',
  listed: 'Listed',
  sold: 'Sold',
  picked: 'Picked',
}

export function itemName(item: { brand: string | null; product: string | null; sku: string }) {
  return [item.brand, item.product].filter(Boolean).join(' ') || item.sku
}
