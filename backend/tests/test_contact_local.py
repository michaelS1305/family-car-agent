import asyncio
import ast
from pathlib import Path
import subprocess
import sys
import unittest
import httpx
from contact_local import app


class LocalContactTests(unittest.TestCase):
    def test_isolated_import_and_lifespan(self):
        code = '''
import sys, asyncio
class Guard:
    def find_spec(self, name, *args):
        if name in ('main', 'database', 'psycopg', 'psycopg_pool', 'account_deletion_api', 'native_push_worker'):
            raise AssertionError('Forbidden dependency')
sys.meta_path.insert(0, Guard())
from contact_local import app
async def check():
    def audit(event, args):
        if event == 'socket.connect': raise AssertionError('External connection')
    sys.addaudithook(audit)
    before = asyncio.all_tasks()
    async with app.router.lifespan_context(app):
        assert asyncio.all_tasks() == before
asyncio.run(check())
'''
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, 'Isolated import/lifespan failed')

    def test_cors_and_readonly_readiness(self):
        async def check():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://local') as client:
                self.assertEqual((await client.get('/health')).status_code, 200)
                for origin, expected in [('http://localhost:5173', 200), ('https://evil.example', 400)]:
                    result = await client.options('/api/contact', headers={'Origin': origin, 'Access-Control-Request-Method': 'POST'})
                    self.assertEqual(result.status_code, expected)
                result = await client.get('/api/contact', headers={'Origin': 'http://localhost:5173'})
                self.assertEqual(result.status_code, 405)
                self.assertEqual(result.headers['access-control-expose-headers'], 'Retry-After')
                self.assertNotIn('access-control-allow-credentials', result.headers)
        asyncio.run(check())

    def test_main_cors(self):
        tree = ast.parse(Path('main.py').read_text(encoding='utf-8'))
        cors = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute) and node.func.attr == 'add_middleware'
                    and node.args and isinstance(node.args[0], ast.Name) and node.args[0].id == 'CORSMiddleware')
        fields = {item.arg: item.value for item in cors.keywords}
        self.assertEqual(ast.literal_eval(fields['expose_headers']), ['Retry-After'])
        self.assertFalse(ast.literal_eval(fields['allow_credentials']))
        self.assertEqual(fields['allow_origins'].func.id, '_cors_allowed_origins')
