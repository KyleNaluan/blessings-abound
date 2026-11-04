import { api } from './client'
import type { components } from './schema'

type Schemas = components['schemas']
export type SettingsPage = Schemas['SettingsRead']
export type SectionKey = keyof SettingsPage
export type BoxSizes = Schemas['BoxSizes']
export type BoxSize = Schemas['BoxSize']
export type SeasonalCalendar = Schemas['SeasonalCalendar']
export type Season = Schemas['Season']
export type WorthListing = Schemas['WorthListing']
export type Fees = Schemas['Fees']
export type ChannelBFees = Schemas['ChannelBFees']
export type AskToSale = Schemas['AskToSale']
export type ShippingWeight = Schemas['ShippingWeight']

const UNREACHABLE = "We couldn't reach the API. Check your connection and try again."

// What to show the person when a call fails, with stale set when another manager saved first.
export class SettingsError extends Error {
  readonly problems: string[]
  readonly stale: boolean

  constructor(problems: string[], stale = false) {
    super(problems.join(' '))
    this.problems = problems
    this.stale = stale
  }
}

type Problem = { loc?: unknown[]; msg?: unknown }

// The list a row sits in, so "Size 2" or "Season 3" says which row a message is about.
const ROW_NAMES: Record<string, string> = { boxes: 'Size', seasons: 'Season' }

function describe(problem: Problem) {
  if (typeof problem.msg !== 'string') return null
  // The API's own checks reach here as pydantic messages, which start with this.
  const message = problem.msg.replace(/^Value error, /, '')
  const loc = problem.loc ?? []
  const list = loc.findIndex((part) => typeof part === 'string' && part in ROW_NAMES)
  const row = loc[list + 1]
  if (list === -1 || typeof row !== 'number') return message
  return `${ROW_NAMES[loc[list] as string]} ${row + 1}: ${message}`
}

async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let result: { data?: T; error?: unknown; response: Response }
  try {
    result = await call
  } catch {
    throw new SettingsError([UNREACHABLE])
  }
  if (result.data !== undefined) return result.data
  const detail = (result.error as { detail?: unknown } | undefined)?.detail
  if (typeof detail === 'string') {
    throw new SettingsError([detail], result.response.status === 409)
  }
  const problems = Array.isArray(detail)
    ? detail.map((problem: Problem) => describe(problem)).filter((text) => text !== null)
    : []
  throw new SettingsError(problems.length ? problems : ['Something went wrong. Try again.'])
}

export function loadSettings() {
  return unwrap(api.GET('/settings'))
}

// Each save sends the time the section was loaded, so the API can refuse one made from a stale page.
type Save<T> = (value: T, expectedUpdatedAt: string | null) => Promise<SettingsPage>

export const saveBoxSizes: Save<BoxSizes> = (value, expected) =>
  unwrap(api.PUT('/settings/box-sizes', { body: { value, expected_updated_at: expected } }))

export const saveSeasonalCalendar: Save<SeasonalCalendar> = (value, expected) =>
  unwrap(api.PUT('/settings/seasonal-calendar', { body: { value, expected_updated_at: expected } }))

export const saveWorthListing: Save<WorthListing> = (value, expected) =>
  unwrap(api.PUT('/settings/worth-listing', { body: { value, expected_updated_at: expected } }))

export const saveFees: Save<Fees> = (value, expected) =>
  unwrap(api.PUT('/settings/fees', { body: { value, expected_updated_at: expected } }))

export const saveChannelBFees: Save<ChannelBFees> = (value, expected) =>
  unwrap(api.PUT('/settings/channel-b-fees', { body: { value, expected_updated_at: expected } }))

export const saveAskToSale: Save<AskToSale> = (value, expected) =>
  unwrap(api.PUT('/settings/ask-to-sale', { body: { value, expected_updated_at: expected } }))

export const saveShippingWeight: Save<ShippingWeight> = (value, expected) =>
  unwrap(api.PUT('/settings/shipping-weight', { body: { value, expected_updated_at: expected } }))
