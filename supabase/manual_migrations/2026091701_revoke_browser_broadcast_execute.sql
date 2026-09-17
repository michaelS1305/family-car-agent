-- MANUAL ONLY. Production execution status is recorded in README.md.
BEGIN;

-- Browser roles do not invoke this trigger function directly.
-- Realtime receive authorization uses can_receive_car_status_topic(text) instead;
-- its privileges, including authenticated EXECUTE, remain unchanged.
REVOKE EXECUTE ON FUNCTION public.broadcast_car_status_changed()
FROM anon, authenticated;

COMMIT;
