-- Additive; apply before deploying the shared-address Backend.
-- Existing sessions keep NULL evidence and are reverified by the new Backend.
-- No existing rows, grants, policies, or RLS settings are changed.
BEGIN;
ALTER TABLE public.pwa_join_sessions
    ADD COLUMN verified_latitude double precision,
    ADD COLUMN verified_longitude double precision,
    ADD COLUMN location_verified_at timestamptz,
    ADD COLUMN location_verification_expires_at timestamptz,
    ADD CONSTRAINT pwa_join_location_verification_check CHECK (
        (verified_latitude IS NULL AND verified_longitude IS NULL
         AND location_verified_at IS NULL AND location_verification_expires_at IS NULL)
        OR
        (verified_latitude IS NOT NULL AND verified_longitude IS NOT NULL
         AND location_verified_at IS NOT NULL AND location_verification_expires_at IS NOT NULL
         AND verified_latitude BETWEEN -90 AND 90
         AND verified_longitude BETWEEN -180 AND 180
         AND isfinite(location_verified_at) AND isfinite(location_verification_expires_at)
         AND location_verification_expires_at = location_verified_at + INTERVAL '15 minutes')
    );
CREATE INDEX pwa_join_location_expiry_idx
    ON public.pwa_join_sessions (location_verification_expires_at)
    WHERE location_verification_expires_at IS NOT NULL;
COMMIT;
