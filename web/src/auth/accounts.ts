import type { Me } from '@/api/accounts'

// What sign-in needs to know about the account model, kept in one place.

export const isEmail = (identifier: string) => identifier.includes('@')

// True until the person chooses their own password. The API refuses them everything else until
// then, so this only decides where the app takes them.
export function mustChoosePassword(me: Me | null): boolean {
  return me?.status === 'temporary_password' || me?.status === 'invited'
}

// Someone with no email has a hidden address on this domain, see api/app/supabase_auth.py, and only the username means anything.
const PLACEHOLDER_SUFFIX = '@accounts.turnstone.invalid'

export function signedInName(email: string | undefined) {
  return email?.endsWith(PLACEHOLDER_SUFFIX) ? email.slice(0, -PLACEHOLDER_SUFFIX.length) : email
}
