import { api } from './client'
import type { components } from './schema'

export type Me = components['schemas']['PersonRead']
export type SignInSession = components['schemas']['SignInSession']

// Who is signed in, or null when the API can't say, which leaves the API's own refusals to speak.
export async function fetchMe(): Promise<Me | null> {
  try {
    const { data } = await api.GET('/me')
    return data ?? null
  } catch {
    return null
  }
}

type Failure = { detail?: unknown }

function detailOf(error: unknown): string | null {
  const detail = (error as Failure | undefined)?.detail
  return typeof detail === 'string' ? detail : null
}

// The API looks the username up and signs in, so the person's address never reaches the browser.
export async function signInWithUsername(username: string, password: string) {
  const { data, error } = await api.POST('/auth/sign-in', { body: { username, password } })
  return data ? { session: data, problem: null } : { session: null, problem: detailOf(error) }
}

// Goes through the API, because only the API can lift the block on a temporary password.
export async function chooseOwnPassword(password: string) {
  const { data, error } = await api.POST('/me/password', { body: { password } })
  return data ? { me: data, problem: null } : { me: null, problem: detailOf(error) }
}
