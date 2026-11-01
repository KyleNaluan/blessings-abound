// Stops a build that would put the service role key into the public JavaScript.
export function checkNoServerSecrets(env: Record<string, string | undefined>) {
  const secret = env.SUPABASE_SERVICE_ROLE_KEY
  for (const [name, value] of Object.entries(env)) {
    if (!name.startsWith('VITE_') || !value) continue
    if (/SERVICE_ROLE/i.test(name) || value === secret) {
      throw new Error(`${name} would put the Supabase service role key in the web bundle.`)
    }
  }
}
