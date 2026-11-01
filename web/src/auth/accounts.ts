import type { Me } from '@/api/accounts'

// What sign-in needs to know about the account model, kept in one place.

export const isEmail = (identifier: string) => identifier.includes('@')

// The address a reset link can go to, or null when all we have is a username.
// The API never tells the browser a username's address, so a person with email types it here.
export async function findResetEmail(identifier: string): Promise<string | null> {
  if (isEmail(identifier)) return identifier
  return null
}

// True until the person chooses their own password. The API refuses them everything else until
// then, so this only decides where the app takes them.
export function mustChoosePassword(me: Me | null): boolean {
  return me?.status === 'temporary_password' || me?.status === 'invited'
}
