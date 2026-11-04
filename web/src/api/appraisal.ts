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

export function uploadPhoto(photo: File) {
  return unwrap(
    api.POST('/items', {
      // The schema types a file part as a string, and the serializer below sends the real file.
      body: { photo: photo as unknown as string },
      bodySerializer: () => {
        const form = new FormData()
        form.append('photo', photo)
        return form
      },
    }),
  )
}

export function createItemCard(itemId: string) {
  return unwrap(
    api.POST('/items/{item_id}/card', {
      params: { path: { item_id: itemId } },
      // PLACEHOLDER: #9 adds the staff entry form, which sends the real condition and other fields.
      body: { condition: 'pre_owned', flaws: [] },
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

export function saveDecision(itemId: string, appraisalId: string, decision: DecisionChoice) {
  return unwrap(
    api.POST('/items/{item_id}/decisions', {
      params: { path: { item_id: itemId } },
      body: { appraisal_id: appraisalId, decision },
    }),
  )
}

export function listRecentDecisions() {
  return unwrap(api.GET('/decisions'))
}

// Drafts the listing for each channel the item's category allows. Asking again returns the same drafts.
export function createListingDrafts(itemId: string) {
  return unwrap(
    api.POST('/items/{item_id}/drafts', {
      params: { path: { item_id: itemId } },
      // PLACEHOLDER: #20 sends the channels staff choose, and the API picks by category until then.
      body: {},
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
