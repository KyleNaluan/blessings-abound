import type { Me } from '@/api/accounts'

// What sign-in needs to know about the account model, kept in one place.

export const isEmail = (identifier: string) => identifier.includes('@')

// True until the person chooses their own password. The API refuses them everything else until
// then, so this only decides where the app takes them.
export function mustChoosePassword(me: Me | null): boolean {
  return me?.status === 'temporary_password' || me?.status === 'invited'
}
