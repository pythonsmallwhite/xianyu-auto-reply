"""离线执行生产广播方法，避免导入 IM 客户端触发真实配置/网络依赖。"""
import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class BroadcastTests(unittest.IsolatedAsyncioTestCase):
    def manager(self):
        source = Path(__file__).resolve().parents[1] / "backend-web/app/services/chat_new/im_session_manager.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ImSessionManager")
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_ensure_push_callback")
        scope = {"asyncio": asyncio, "json": json, "logger": Mock(), "GoofishImClient": object}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), scope)
        manager = SimpleNamespace(_ws_clients={})
        client = SimpleNamespace(add_push_callback=Mock())
        scope["_ensure_push_callback"](manager, "account", client)
        return manager, client.add_push_callback.call_args.args[0]

    async def test_subscription_mutation_during_broadcast_delivers_to_snapshot(self):
        manager, forward = self.manager()
        received = []
        class Socket:
            async def send_text(self, payload):
                manager._ws_clients["account"].add(object())
                await asyncio.sleep(0)
                received.append(json.loads(payload))
        manager._ws_clients["account"] = {Socket(), Socket()}
        await forward({"event": "new_message"})
        self.assertEqual(received, [{"event": "new_message"}] * 2)

    async def test_failed_old_socket_cannot_remove_replacement_subscription(self):
        manager, forward = self.manager()
        replacement = {object()}
        class Socket:
            async def send_text(self, payload):
                manager._ws_clients["account"] = replacement
                raise ConnectionError("closed")
        manager._ws_clients["account"] = {Socket()}
        await forward({"event": "new_message"})
        self.assertIs(manager._ws_clients["account"], replacement)

    async def test_failed_socket_does_not_prevent_healthy_delivery(self):
        manager, forward = self.manager()
        received = []
        class Healthy:
            async def send_text(self, payload):
                received.append(payload)
        class Failed:
            async def send_text(self, payload):
                raise ConnectionError("closed")
        healthy = Healthy()
        manager._ws_clients["account"] = {healthy, Failed()}
        await forward({"event": "new_message"})
        self.assertEqual(len(received), 1)
        self.assertEqual(manager._ws_clients["account"], {healthy})
