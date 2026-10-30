import { createClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

// Null in a copy of the app without Supabase settings, so the public pages still load and sign-in can say why it can't work.
// The anon key is public by design, and row-level security decides what it can read.
export const supabase = url && anonKey ? createClient(url, anonKey) : null
