"""Local MCP server over real stdio (projects/mcp-local/PLAN.md Step 2).

Run from the project root:  py -m unittest tests.test_mcp_stdio -v
Starts `python -m mcp_local` as Claude Code would, against a temp data folder (CM_DATA_DIR).
"""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

from core.db import Database

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError:                      # lean remote sessions: pip install mcp==1.28.1 to run this
    stdio_client = None

ROOT = Path(__file__).resolve().parent.parent
READ_TOOLS = {'library_stats', 'search_library', 'list_items', 'show_item', 'read_item_file',
              'list_notes', 'search_notes', 'read_note', 'list_topics', 'read_topic'}


async def _talk(data_dir):
    params = StdioServerParameters(command=sys.executable, args=['-m', 'mcp_local'],
                                   env={'CM_DATA_DIR': str(data_dir)}, cwd=str(ROOT))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            names = {t.name for t in (await session.list_tools()).tools}
            stats = await session.call_tool('library_stats', {})
            found = await session.call_tool('search_library', {'query': 'pasta', 'semantic': False})
            bad = await session.call_tool('read_item_file', {'item_id': 1, 'name': '../content_manager.db'})
            return names, stats, found, bad


@unittest.skipIf(stdio_client is None, 'mcp SDK not installed')
class StdioTest(unittest.TestCase):
    def test_read_tools_over_stdio(self):
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        db = Database(Path(td.name) / 'content_manager.db')
        db.add_item({'url': 'https://youtu.be/a', 'description': 'pasta carbonara recipe'})
        db.add_item({'url': 'https://youtu.be/b', 'description': 'bike repair basics'})
        db.close()
        names, stats, found, bad = asyncio.run(_talk(td.name))
        self.assertTrue(READ_TOOLS <= names, names)
        self.assertEqual(json.loads(stats.content[0].text)['items'], 2)
        self.assertEqual(json.loads(found.content[0].text)['count'], 1)
        self.assertTrue(bad.isError)


if __name__ == '__main__':
    unittest.main()
