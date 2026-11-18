-- Stage 1 only. Apply manually to Development after review; no automatic execution.
BEGIN;
CREATE TABLE public.apple_credential_attempts (
    generation bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    auth_user_id uuid NOT NULL,
    code_digest bytea NOT NULL CHECK (octet_length(code_digest)=32),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','stored')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(auth_user_id, code_digest)
);
CREATE INDEX apple_credential_attempts_owner_time ON public.apple_credential_attempts(auth_user_id,created_at);
CREATE TABLE public.apple_credentials (
    auth_user_id uuid PRIMARY KEY,
    environment text NOT NULL CHECK (environment='dev'),
    client_id text NOT NULL CHECK (client_id='com.familycaragent.app.dev'),
    apple_subject text NOT NULL,
    generation bigint NOT NULL REFERENCES public.apple_credential_attempts(generation),
    key_id text NOT NULL,
    refresh_ciphertext bytea NOT NULL CHECK (octet_length(refresh_ciphertext)>28),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
-- Deliberately no cascading auth/users FK: later revocation must survive FCA cleanup.
-- No user-facing read endpoints or RLS policies. Backend DB role only.
ALTER TABLE public.apple_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.apple_credential_attempts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.apple_credentials, public.apple_credential_attempts FROM PUBLIC, anon, authenticated;
REVOKE ALL ON SEQUENCE public.apple_credential_attempts_generation_seq FROM PUBLIC, anon, authenticated;
COMMIT;
