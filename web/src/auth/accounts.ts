import type { User } from '@supabase/supabase-js'

// What sign-in needs to know about the account model, kept in one place because issue #31 (invite-only accounts) defines that
// model and hasn't landed yet. #31 adds usernames, the hidden placeholder address behind an account without email, and the
// temporary-password flag, and only these functions should need to change when it does.

const isEmail = (identifier: string) => identifier.includes('@')

// The address Supabase Auth knows this person by, or null when no account can match.
export async function findSignInEmail(identifier: string): Promise<string | null> {
  if (isEmail(identifier)) return identifier
  // No account has a username until #31's profiles table exists, so a username can't match one yet.
  return null
}

// The address a reset link can go to, or null when the account has no email of its own.
// After #31 this differs from findSignInEmail for people without email, whose sign-in address is a placeholder.
export async function findResetEmail(identifier: string): Promise<string | null> {
  if (isEmail(identifier)) return identifier
  return null
}

// Set by whoever issues a temporary password, and cleared when the person chooses their own.
export const TEMPORARY_PASSWORD_FLAG = 'temporary_password'

export function hasTemporaryPassword(user: User): boolean {
  return user.user_metadata?.[TEMPORARY_PASSWORD_FLAG] === true
}
