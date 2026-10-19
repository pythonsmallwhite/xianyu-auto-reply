"""Offline contract tests for the b1724 chat subscription guard."""
import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

ROOT = Path(__file__).resolve().parents[1]
ROUTE = ROOT / 'backend-web/app/api/routes/chat_new_ws.py'


class WebSocketDisconnect(Exception):
    pass


def load_functions(names):
    tree = ast.parse(ROUTE.read_text(encoding='utf-8-sig'))
    selected = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name in names]
    scope = {
        'json': json, 'logger': Mock(), 'WebSocketDisconnect': WebSocketDisconnect,
        'WebSocket': object,
        'ImSessionManager': object,
        'WS_CLOSE_IM_OFFLINE': 4404,
    }
    module = ast.Module(body=selected, type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(ROUTE), 'exec'), scope)
    return scope


class FakeSocket:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.sent = []
        self.closed = []

    async def receive_text(self):
        try:
            return next(self.messages)
        except StopIteration:
            raise WebSocketDisconnect()

    async def send_text(self, payload):
        self.sent.append(json.loads(payload))

    async def close(self, code=None):
        self.closed.append(code)


class ChatNewWsOfflineTests(unittest.IsolatedAsyncioTestCase):
    async def test_ping_closes_when_im_client_disappears(self):
        scope = load_functions({'_receive_loop'})
        socket = FakeSocket([json.dumps({'type': 'ping'})])
        manager = SimpleNamespace(clients={'account': SimpleNamespace(is_connected=False)})
        await scope['_receive_loop'](socket, 'account', manager)
        self.assertEqual(socket.closed, [4404])
        self.assertEqual(socket.sent, [])

    async def test_ping_replies_when_im_client_is_connected(self):
        scope = load_functions({'_receive_loop'})
        socket = FakeSocket([json.dumps({'type': 'ping'})])
        manager = SimpleNamespace(clients={'account': SimpleNamespace(is_connected=True)})
        with self.assertRaises(WebSocketDisconnect):
            await scope['_receive_loop'](socket, 'account', manager)
        self.assertEqual(socket.sent, [{'event': 'pong'}])
        self.assertEqual(socket.closed, [])

    async def test_source_contract_checks_before_subscription(self):
        source = ROUTE.read_text(encoding='utf-8-sig')
        self.assertIn('WS_CLOSE_IM_OFFLINE = 4404', source)
        self.assertIn('client = manager.clients.get(account_id)', source)
        self.assertIn('await websocket.close(code=WS_CLOSE_IM_OFFLINE)', source)
        self.assertIn('_receive_loop(websocket, account_id, manager)', source)


if __name__ == '__main__':
    unittest.main()
