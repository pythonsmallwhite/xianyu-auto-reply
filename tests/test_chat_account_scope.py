import ast
import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace


ROUTE_PATH = (
    Path(__file__).resolve().parents[1]
    / "backend-web"
    / "app"
    / "api"
    / "routes"
    / "chat_new.py"
)


class ChatAccountScopeTests(unittest.TestCase):
    def test_unowned_account_never_reaches_shared_im_client(self):
        source = ast.parse(ROUTE_PATH.read_text(encoding="utf-8-sig"))
        names = {"disconnect_account", "get_conversations", "get_messages", "send_message"}
        functions = [
            node for node in source.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name in names
        ]
        self.assertEqual({node.name for node in functions}, names)
        for function in functions:
            function.decorator_list = []

        async def deny_account(account_id, current_user, db):
            return None

        def forbidden_manager():
            raise AssertionError("shared IM manager accessed before account ownership check")

        namespace = {
            "Depends": lambda dependency: None,
            "get_current_active_user": object(),
            "get_db_session": object(),
            "ApiResponse": lambda **fields: SimpleNamespace(**fields),
            "get_im_session_manager": forbidden_manager,
            "_get_owned_chat_account": deny_account,
        }
        module = ast.Module(
            body=[
                ast.ImportFrom(
                    module="__future__",
                    names=[ast.alias(name="annotations")],
                    level=0,
                ),
                *functions,
            ],
            type_ignores=[],
        )
        ast.fix_missing_locations(module)
        exec(compile(module, str(ROUTE_PATH), "exec"), namespace)

        user = SimpleNamespace(id=1)
        db = object()
        requests = {
            "disconnect_account": ("other-account",),
            "get_conversations": ("other-account",),
            "get_messages": ("other-account", "chat-id"),
            "send_message": ("other-account", SimpleNamespace(text="private message")),
        }
        for name, args in requests.items():
            with self.subTest(route=name):
                result = asyncio.run(namespace[name](*args, current_user=user, db=db))
                self.assertFalse(result.success)
                self.assertIn("无权", result.message)


class ChatHistoryErrorTests(unittest.TestCase):
    def test_upstream_error_is_not_an_empty_success(self):
        from unittest.mock import AsyncMock, Mock
        tree = ast.parse(ROUTE_PATH.read_text(encoding="utf-8-sig"))
        fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "get_messages")
        fn.decorator_list = []
        scope = {
            "Depends": lambda dependency: None,
            "get_current_active_user": object(), "get_db_session": object(),
            "ApiResponse": lambda **fields: SimpleNamespace(**fields),
            "_get_owned_chat_account": AsyncMock(return_value=True),
            "get_im_session_manager": lambda: SimpleNamespace(clients={"a": SimpleNamespace(
                is_connected=True, get_messages=AsyncMock(return_value={"reason": "temporary"}))}),
            "logger": Mock(),
        }
        module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), fn], type_ignores=[])
        ast.fix_missing_locations(module)
        exec(compile(module, str(ROUTE_PATH), "exec"), scope)
        result = asyncio.run(scope["get_messages"]("a", "cid", current_user=object(), db=object()))
        self.assertFalse(result.success)
        self.assertIn("暂时不可用", result.message)


if __name__ == "__main__":
    unittest.main()
