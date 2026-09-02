import { createClient, type SupabaseClient } from '@supabase/supabase-js'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL?.trim()
const supabasePublicKey = (
  import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY
  ?? import.meta.env.VITE_SUPABASE_ANON_KEY
)?.trim()

let client: SupabaseClient | undefined

export class SupabaseConfigurationError extends Error {
  constructor() {
    super('Supabase Auth is not configured')
    this.name = 'SupabaseConfigurationError'
  }
}

export function getSupabaseClient() {
  if (!supabaseUrl || !supabasePublicKey) {
    throw new SupabaseConfigurationError()
  }

  client ??= createClient(supabaseUrl, supabasePublicKey, {
    auth: {
      autoRefreshToken: true,
      detectSessionInUrl: true,
      flowType: 'pkce',
      persistSession: true,
    },
  })

  return client
}
