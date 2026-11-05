import { api } from './client'
import type { components } from './schema'

export type Item = components['schemas']['ItemRead']
export type ItemCard = components['schemas']['ItemCardRead']
export type ItemCardEdit = components['schemas']['ItemCardEdit']
export type Appraisal = components['schemas']['AppraisalRead']
export type DecisionChoice = components['schemas']['DecisionChoice']
export type RecentDecision = components['schemas']['RecentDecision']
export type ListingDraft = components['schemas']['ListingDraftRead']
export type ListingDraftEdit = components['schemas']['ListingDraftEdit']
export type Channel = components['schemas']['Channel']
export type ChannelRecommendation = components['schemas']['ChannelRecommendation']
export type StoreDepartment = components['schemas']['StoreDepartment']
export type ItemCardRequest = components['schemas']['ItemCardRequest']
export type Destination = components['schemas']['Destination']
export type RejectedMatch = components['schemas']['RejectedMatch']

const UNREACHABLE = "We couldn't reach the API. Check your connection and try again."

// Returns the data from a call, or throws with what to show the person.
async function unwrap<T>(call: Promise<{ data?: T; error?: unknown }>): Promise<T> {
  let result: { data?: T; error?: unknown }
  try {
    result = await call
  } catch {
    throw new Error(UNREACHABLE)
  }
  if (result.data !== undefined) return result.data
  const detail = (result.error as { detail?: unknown } | undefined)?.detail
  throw new Error(typeof detail === 'string' ? detail : 'Something went wrong. Try again.')
}

// What staff give at intake, before the item has a record.
export type NewItem = { photos: File[]; storeDepartment: StoreDepartment; notes: string }

// A photo matched an item that was rejected before, and staff haven't chosen to take it in anyway.
export class RepeatPhotoError extends Error {
  readonly matches: RejectedMatch[]

  constructor(message: string, matches: RejectedMatch[]) {
    super(message)
    this.matches = matches
  }
}

// Takes the item in, which stores its photos and gives it a SKU.
export async function takeItemIn(item: NewItem, allowRepeat = false) {
  const call = api.POST('/items', {
    body: {
      store_department: item.storeDepartment,
      // The schema types a file part as a string, and the serializer below sends the real files.
      photos: item.photos as unknown as string[],
      notes: item.notes,
      allow_repeat: allowRepeat,
    },
    bodySerializer: () => {
      const form = new FormData()
      for (const photo of item.photos) form.append('photos', photo)
      form.append('store_department', item.storeDepartment)
      if (item.notes.trim()) form.append('notes', item.notes.trim())
      form.append('allow_repeat', String(allowRepeat))
      return form
    },
  })
  let result: Awaited<typeof call>
  try {
    result = await call
  } catch {
    throw new Error(UNREACHABLE)
  }
  if (result.response.status === 409) {
    const { detail } = result.error as components['schemas']['RepeatPhotoConflict']
    throw new RepeatPhotoError(detail.message, detail.matches)
  }
  return unwrap(Promise.resolve(result))
}

export function createItemCard(itemId: string, entries: ItemCardRequest) {
  return unwrap(
    api.POST('/items/{item_id}/card', {
      params: { path: { item_id: itemId } },
      body: entries,
    }),
  )
}

export function confirmItemCard(itemId: string, edit: ItemCardEdit) {
  return unwrap(
    api.PATCH('/items/{item_id}/card', {
      params: { path: { item_id: itemId } },
      body: edit,
    }),
  )
}

export function createAppraisal(itemId: string) {
  return unwrap(api.POST('/items/{item_id}/appraisals', { params: { path: { item_id: itemId } } }))
}

// Where a rejected item goes and why, which a no needs and a yes leaves out.
export type Rejection = { reason: string; destination: Destination }

export function saveDecision(
  itemId: string,
  appraisalId: string,
  decision: DecisionChoice,
  rejection?: Rejection,
) {
  return unwrap(
    api.POST('/items/{item_id}/decisions', {
      params: { path: { item_id: itemId } },
      body: {
        appraisal_id: appraisalId,
        decision,
        ...(rejection && {
          rejection_reason: rejection.reason,
          destination: rejection.destination,
        }),
      },
    }),
  )
}

export function listRecentDecisions() {
  return unwrap(api.GET('/decisions'))
}

// Which channels can take the item and whether to list it now or hold it for its season.
export function getChannelRecommendation(itemId: string) {
  return unwrap(api.GET('/items/{item_id}/channels', { params: { path: { item_id: itemId } } }))
}

// Drafts the listing for each channel staff chose. Asking again returns the same drafts.
export function createListingDrafts(itemId: string, channels: Channel[]) {
  return unwrap(
    api.POST('/items/{item_id}/drafts', {
      params: { path: { item_id: itemId } },
      body: { channels },
    }),
  )
}

export function editListingDraft(itemId: string, channel: Channel, edit: ListingDraftEdit) {
  return unwrap(
    api.PATCH('/items/{item_id}/drafts/{channel}', {
      params: { path: { item_id: itemId, channel } },
      body: edit,
    }),
  )
}

export function submitListingDrafts(itemId: string) {
  return unwrap(
    api.POST('/items/{item_id}/drafts/submit', { params: { path: { item_id: itemId } } }),
  )
}
