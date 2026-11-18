"""Focused Apple/deletion checks with provider and database I/O explicitly disabled."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def forbidden(*args, **kwargs):
    raise AssertionError("External I/O forbidden in offline push checks")

if __name__ == '__main__':
    system = {k:v for k,v in os.environ.items() if k.upper() in ('SYSTEMROOT','WINDIR','PATH','TEMP','TMP','COMSPEC','PATHEXT')}
    with patch.dict(os.environ, {**system,
        'DATABASE_URL':'postgresql://unused:unused@127.0.0.1:1/test_gemini',
        'SUPABASE_URL':'https://invalid.example', 'SUPABASE_SERVICE_ROLE_KEY':'synthetic',
        'GEMINI_API_KEY':'synthetic', 'GOOGLE_API_KEY':'synthetic',
        'GEMINI_TEST_DATABASE_URL':'', 'NATIVE_PUSH_ENABLED':'false',
    }, clear=True), patch('dotenv.load_dotenv'), \
         patch('psycopg_pool.ConnectionPool', return_value=Mock()), \
         patch('psycopg.connect', side_effect=forbidden), \
         patch('requests.sessions.Session.request', side_effect=forbidden), \
         patch('socket.create_connection', side_effect=forbidden):
        suite = unittest.TestSuite()
        for pattern in ('test_apple*.py', 'test_account_deletion*.py', 'test_deletion_gate*.py'):
            suite.addTests(unittest.defaultTestLoader.discover(str(Path(__file__).parent), pattern=pattern))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        sys.exit(not result.wasSuccessful())
