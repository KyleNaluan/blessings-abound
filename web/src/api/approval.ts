import { api } from './client'
import type { components } from './schema'

type Schemas = components['schemas']
export type ApprovalQueue = Schemas['ApprovalQueue']
export type QueueItem = Schemas['QueueItem']
export type ItemReview = Schemas['ItemReview']
export type ListingReview = Schemas['ListingReview']
export type PickListEntry = Schemas['PickListEntry']
export type BoxSizeOption = Schemas['BoxSizeOption']
export type ItemStatus = Schemas['ItemStatus']
export type Channel = Schemas['Channel']
export type ListingStatus = Schemas['ListingStatus']
export type HistoryEntry = Schemas['HistoryEntry']
export type NotOnlineResult = Schemas['NotOnlineResult']

const UNREACHABLE = "We couldn't reach the API. Check your connection and try again."

type Result<T> = { data?: T; error?: unknown; response: Response }

function message(error: unknown) {
  const detail = (error as { detail?: unknown } | undefined)?.detail
  if (typeof detail === 'string') return detail
  // A request the API's own model refused, where each problem has a message.
  if (Array.isArray(detail)) {
    const problems = detail
      .map((problem: { msg?: unknown }) => problem.msg)
      .filter((text): text is string => typeof text === 'string')
      .map((text) => text.replace(/^Value error, /, ''))
    if (problems.length) return problems.join(' ')
  }
  return 'Something went wrong. Try again.'
}

async function send<T>(call: Promise<Result<T>>): Promise<Result<T>> {
  try {
    return await call
  } catch {
    throw new Error(UNREACHABLE)
  }
}

// Returns the data from a call, or throws with what to show the person.
export async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  const result = await send(call)
  if (result.data !== undefined) return result.data
  throw new Error(message(result.error))
}

// For a call that answers with no body when it works.
async function done(call: Promise<Result<unknown>>): Promise<void> {
  const result = await send(call)
  if (!result.response.ok) throw new Error(message(result.error))
}

export function loadApprovals() {
  return unwrap(api.GET('/approvals'))
}

export function loadItemReview(itemId: string) {
  return unwrap(api.GET('/items/{item_id}/review', { params: { path: { item_id: itemId } } }))
}

// The box sizes in Settings, in the order the manager keeps them.
export function loadBoxSizes() {
  return unwrap(api.GET('/settings/box-sizes'))
}

// A null price puts the channel back on the appraisal's typical sale price.
export function setListingPrice(itemId: string, channel: Channel, cents: number | null) {
  return unwrap(
    api.PUT('/items/{item_id}/listings/{channel}/price', {
      params: { path: { item_id: itemId, channel } },
      body: { price_override_cents: cents },
    }),
  )
}

export function saveStorage(
  itemId: string,
  storage: { package_weight_oz: number; box_code: string; location_code?: string | null },
) {
  return unwrap(
    api.PUT('/items/{item_id}/storage', {
      params: { path: { item_id: itemId } },
      body: storage,
    }),
  )
}

export function approveItem(itemId: string) {
  return unwrap(api.POST('/items/{item_id}/approve', { params: { path: { item_id: itemId } } }))
}

export function rejectItem(itemId: string, reason: string, note: string) {
  return unwrap(
    api.POST('/items/{item_id}/reject', {
      params: { path: { item_id: itemId } },
      body: { reason, note: note || null },
    }),
  )
}

// Brings a held item into the review before its release month comes.
export function listNow(itemId: string) {
  return unwrap(api.POST('/items/{item_id}/list-now', { params: { path: { item_id: itemId } } }))
}

// Takes the item out of online selling for good, with a note on why.
export function keepOffOnline(itemId: string, note: string) {
  return unwrap(
    api.POST('/items/{item_id}/not-online', {
      params: { path: { item_id: itemId } },
      body: { note },
    }),
  )
}

// Looks up comparable sales again for a held item back for review, then answers with the review.
export function lookUpFreshComps(itemId: string) {
  return unwrap(api.POST('/items/{item_id}/fresh-comps', { params: { path: { item_id: itemId } } }))
}

// Sends the listings a channel refused or couldn't take again, then answers with the review.
export async function publishAgain(itemId: string) {
  await unwrap(api.POST('/items/{item_id}/listings', { params: { path: { item_id: itemId } } }))
  return loadItemReview(itemId)
}

export function loadPickList() {
  return unwrap(api.GET('/pick-list'))
}

export function markPicked(itemId: string) {
  return done(api.POST('/items/{item_id}/picked', { params: { path: { item_id: itemId } } }))
}
