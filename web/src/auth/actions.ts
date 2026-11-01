import type { AuthError } from '@supabase/supabase-js'

import { findResetEmail, findSignInEmail, TEMPORARY_PASSWORD_FLAG } from './accounts'
import { supabase } from './supabase'

// Each action resolves to an error message to show, or null when it worked.

const NOT_SET_UP = "Sign-in isn't set up on this copy of Turnstone yet."
const UNREACHABLE = "We couldn't reach the sign-in service. Try again in a minute."
export const WRONG_DETAILS = 'Your username, email or password is wrong'

function message(error: AuthError | null, known: Partial<Record<string, string>> = {}) {
  if (!error) return null
  return (error.code && known[error.code]) || UNREACHABLE
}

export async function signIn(identifier: string, password: string): Promise<string | null> {
  if (!supabase) return NOT_SET_UP
  const email = await findSignInEmail(identifier)
  if (!email) return WRONG_DETAILS
  const { error } = await supabase.auth.signInWithPassword({ email, password })
  return message(error, {
    invalid_credentials: WRONG_DETAILS,
    user_banned: 'This account is turned off. Ask a store manager to turn it back on.',
    email_not_confirmed: "This account isn't set up yet. Ask a store manager to finish it.",
  })
}

// Sends a reset link when the account has an email. The answer is the same either way, so nobody can use this page to find
// out which accounts exist.
export async function sendPasswordReset(identifier: string): Promise<string | null> {
  if (!supabase) return NOT_SET_UP
  const email = await findResetEmail(identifier)
  if (!email) return null
  const { error } = await supabase.auth.resetPasswordForEmail(email, {
    redirectTo: `${window.location.origin}/choose-password`,
  })
  // Supabase's built-in mailer refuses test domains and, without a custom SMTP server, anyone outside the project team.
  const undeliverable =
    "We couldn't send an email to that address. Ask a store manager to give you a temporary password."
  return message(error, {
    over_email_send_rate_limit: 'Too many reset emails were sent. Try again in an hour.',
    email_address_invalid: undeliverable,
    email_address_not_authorized: undeliverable,
  })
}

export async function choosePassword(password: string): Promise<string | null> {
  if (!supabase) return NOT_SET_UP
  const { error } = await supabase.auth.updateUser({
    password,
    data: { [TEMPORARY_PASSWORD_FLAG]: false },
  })
  return message(error, {
    same_password: 'Choose a password that is different from your current one',
    weak_password: 'Choose a stronger password, such as a few words in a row',
  })
}

export async function signOut(): Promise<string | null> {
  if (!supabase) return null
  try {
    const { error } = await supabase.auth.signOut()
    return message(error)
  } catch {
    return UNREACHABLE
  }
}
