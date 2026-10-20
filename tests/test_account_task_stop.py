import ast
import asyncio
import sys
import types
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "backend-web/app/api/routes/cookies.py"


def load_functions():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    names = {"_request_stop_account_task", "_update_account_status_and_task"}
    nodes = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name in names]
    assert {node.name for node in nodes} == names

    real_wait_for = asyncio.wait_for

    async def fast_wait_for(awaitable, timeout):
        return await real_wait_for(awaitable, timeout=0.01)

    namespace = {
        "asyncio": types.SimpleNamespace(wait_for=fast_wait_for, TimeoutError=asyncio.TimeoutError),
        "_status_to_enabled": lambda status: status not in {"inactive", "disabled"},
        "XYAccount": object,
        "AccountService": object,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace


class StopTaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_timeout_is_bounded_and_reported(self):
        funcs = load_functions()
        cancelled = asyncio.Event()

        class WebSocketClient:
            async def stop_account(self, account_id):
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()

        ok, message = await funcs["_request_stop_account_task"](WebSocketClient(), "acc1")

        self.assertFalse(ok)
        self.assertEqual(message, "后台任务停止请求超时")
        self.assertTrue(cancelled.is_set())

    async def test_disable_keeps_account_disabled_when_stop_times_out(self):
        funcs = load_functions()
        account = types.SimpleNamespace(
            account_id="acc1", cookie="cookie", owner_id=1, status="active", disable_reason=None
        )
        updates = []

        class AccountService:
            async def update_status(self, current, enabled, disable_reason=None):
                updates.append((enabled, disable_reason))
                current.status = "active" if enabled else "inactive"
                current.disable_reason = disable_reason

        async def never_stops(_account_id):
            await asyncio.Event().wait()

        module = types.ModuleType("app.services.websocket_client")
        module.websocket_client = types.SimpleNamespace(stop_account=never_stops)
        old_module = sys.modules.get("app.services.websocket_client")
        sys.modules["app.services.websocket_client"] = module
        try:
            ok, message = await funcs["_update_account_status_and_task"](
                account, False, AccountService()
            )
        finally:
            if old_module is None:
                sys.modules.pop("app.services.websocket_client", None)
            else:
                sys.modules["app.services.websocket_client"] = old_module

        self.assertTrue(ok)
        self.assertIn("账号已禁用", message)
        self.assertEqual(account.status, "inactive")
        self.assertEqual(len(updates), 1, "停止超时不能把账号状态回滚为启用")


if __name__ == "__main__":
    unittest.main()
