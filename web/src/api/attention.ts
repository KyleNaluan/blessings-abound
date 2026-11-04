import { unwrap } from './approval'
import { api } from './client'
import type { components } from './schema'

type Schemas = components['schemas']
export type Attention = Schemas['AttentionRead']
export type Flag = Schemas['FlagRead']
export type ConflictKind = Schemas['ConflictKind']

export function loadAttention() {
  return unwrap(api.GET('/attention'))
}

// Cancels the later order of a double sale on its channel, and answers with the flag as it is
// after the channel's answer: resolved, or with the cancel still being tried.
export function fixDoubleSale(flagId: string) {
  return unwrap(api.POST('/attention/{flag_id}/fix', { params: { path: { flag_id: flagId } } }))
}

export function markHandled(flagId: string, note: string) {
  return unwrap(
    api.POST('/attention/{flag_id}/resolve', {
      params: { path: { flag_id: flagId } },
      body: { note },
    }),
  )
}
