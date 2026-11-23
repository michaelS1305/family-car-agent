"""Apply exact additive migrations inside an already guarded disposable schema."""
from pathlib import Path


def apply(query, schema):
    root = Path(__file__).resolve().parents[2] / 'supabase/manual_migrations'
    for name in ('2026112201_return_recovery.sql','2026112301_return_current_state_reconciliation.sql'):
        source = (root/name).read_text()
        query(source.replace('public.',schema+'.').replace('BEGIN;','').replace('COMMIT;',''))
