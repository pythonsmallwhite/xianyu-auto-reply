"""Execute production connection/login methods with offline transports and SQLite."""
import ast
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import json
import time

ROOT = Path(__file__).resolve().parents[1]
CLIENT = 'backend-web/app/services/chat_new/im_client.py'
MANAGER = 'backend-web/app/services/chat_new/im_session_manager.py'
ACCOUNT = 'backend-web/app/services/account_service.py'


def load_definitions(path, names, scope, class_name=None):
    nodes = ast.parse((ROOT / path).read_text(encoding='utf-8-sig')).body
    if class_name:
        nodes = next(n for n in nodes if isinstance(n, ast.ClassDef) and n.name == class_name).body
    selected = [n for n in nodes if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    assert {n.name for n in selected} == set(names)
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *selected], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), path, 'exec'), scope)
    return scope


def cookie_values(value):
    return dict(part.strip().split('=', 1) for part in value.split(';') if '=' in part)


class ConnectionRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.scope = {'asyncio': asyncio, 'json': json, 'time': time, 'logger': Mock(),
                      'trans_cookies': cookie_values, 'generate_device_id': lambda uid: 'test-device',
                      'generate_mid': lambda: 'test-mid', 'DEFAULT_MEDIA_HOST': 'unused',
                      'TOKEN_INVALID_LWP_CODES': (400,), 'REQUEST_TIMEOUT': 1, 'WS_URL': 'offline',
                      'mark_token_cache_expired': AsyncMock(return_value=SimpleNamespace(success=True, message='expired'))}
        load_definitions(CLIENT, {'GoofishImClient', 'ImRequestRejected'}, self.scope)
        self.Client = self.scope['GoofishImClient']
        self.Rejected = self.scope['ImRequestRejected']
        self.client = self.Client('offline-account', 'unb=offline-user', account_row_id=7)

    async def test_initial_registration_rejection_refreshes_once(self):
        async def attempt():
            self.client.token = 'old-token' if once.await_count == 1 else 'new-token'
            self.client._registration_token_invalid = once.await_count == 1
            return once.await_count == 2
        once = AsyncMock(side_effect=attempt)
        self.client._connect_once = once
        self.assertTrue(await self.client.connect())
        self.assertEqual(once.await_count, 2)
        self.scope['mark_token_cache_expired'].assert_awaited_once_with(
            token_user_id='chat_offline-user', expected_token='old-token', expected_device_id='test-device')

    async def test_repeated_registration_rejection_is_bounded_and_expires_last_token(self):
        async def reject():
            self.client.token = f'rejected-{once.await_count}'
            self.client._registration_token_invalid = True
            return False
        once = AsyncMock(side_effect=reject)
        self.client._connect_once = once
        self.assertFalse(await self.client.connect())
        self.assertEqual(once.await_count, 2)
        self.assertEqual(self.scope['mark_token_cache_expired'].await_count, 2)

    async def test_network_error_does_not_invalidate_or_retry_token(self):
        self.client._connect_once = AsyncMock(return_value=False)
        self.assertFalse(await self.client.connect())
        self.client._connect_once.assert_awaited_once()
        self.scope['mark_token_cache_expired'].assert_not_awaited()

    async def test_invalidation_failure_does_not_reuse_rejected_cache(self):
        async def reject():
            self.client.token = 'rejected'
            self.client._registration_token_invalid = True
            return False
        self.client._connect_once = AsyncMock(side_effect=reject)
        self.scope['mark_token_cache_expired'].return_value.success = False
        self.assertFalse(await self.client.connect())
        self.client._connect_once.assert_awaited_once()
        self.assertIn('缓存失败', self.client.last_connect_error)

    async def test_registration_requires_confirmation_before_sync(self):
        for response in ({'code': 403, 'body': {}}, {'body': {}}, {'code': 400}):
            self.client._send_and_wait = AsyncMock(return_value=response)
            self.client._send_raw = AsyncMock()
            with self.assertRaises(self.Rejected):
                await self.client._register()
            self.client._send_raw.assert_not_awaited()
        self.client._send_and_wait = AsyncMock(return_value={'code': 200})
        self.client._send_raw = AsyncMock()
        with patch.object(asyncio, 'sleep', new=AsyncMock()):
            await self.client._register()
        self.assertEqual(self.client._send_raw.await_args.args[0]['lwp'], '/r/SyncStatus/ackDiff')

    async def test_registration_timeout_never_sends_sync_or_reports_success(self):
        self.client._send_and_wait = AsyncMock(side_effect=TimeoutError('offline timeout'))
        self.client._send_raw = AsyncMock()
        with self.assertRaises(TimeoutError):
            await self.client._register()
        self.client._send_raw.assert_not_awaited()

    async def test_connect_reports_safe_stage_and_cleans_resources(self):
        ws = SimpleNamespace(closed=False)
        session = SimpleNamespace(ws_connect=AsyncMock(return_value=ws))
        self.scope['aiohttp'] = SimpleNamespace(ClientSession=lambda: session, ClientTimeout=lambda **kw: kw)
        self.client._get_im_token = AsyncMock(return_value='private-token')
        self.client._recv_loop = AsyncMock()
        self.client._register = AsyncMock(side_effect=self.Rejected('private-token; private-cookie', 400))
        self.client.disconnect = AsyncMock()
        self.assertFalse(await self.client._connect_once())
        self.assertEqual(self.client.last_connect_error, '注册聊天会话被拒绝（code=400）')
        self.assertNotIn('private', self.client.last_connect_error)
        self.client.disconnect.assert_awaited_once()
        await asyncio.sleep(0)

    async def test_missing_token_has_meaningful_error(self):
        self.client._get_im_token = AsyncMock(return_value='')
        self.assertFalse(await self.client._connect_once())
        self.assertIn('Token', self.client.last_connect_error)

    async def test_manager_rebuilds_old_login_but_reuses_unchanged_connection(self):
        self.scope['GoofishImClient'] = Mock()
        load_definitions(MANAGER, {'ImSessionManager'}, self.scope)
        manager = self.scope['ImSessionManager']()
        manager._get_account_context = AsyncMock(return_value=(8, 'unb=offline-user; new=login'))
        fresh = SimpleNamespace(connect=AsyncMock(return_value=True), last_connect_error='', is_connected=True)
        self.scope['GoofishImClient'].return_value = fresh
        manager._setup_push_callback_after_connect = AsyncMock()
        old = SimpleNamespace(is_connected=True, account_row_id=7, cookies_str='unb=offline-user', disconnect=AsyncMock())
        manager.clients['offline-account'] = old
        self.assertIs(await manager.get_or_connect('offline-account'), fresh)
        old.disconnect.assert_awaited_once()
        fresh.account_row_id = 8
        fresh.cookies_str = 'unb=offline-user; new=login'
        self.assertIs(await manager.get_or_connect('offline-account'), fresh)
        fresh.connect.assert_awaited_once()

    async def test_manager_does_not_return_deleted_account_or_hide_failure(self):
        load_definitions(MANAGER, {'ImSessionManager'}, self.scope)
        manager = self.scope['ImSessionManager']()
        old = SimpleNamespace(disconnect=AsyncMock())
        manager.clients['offline-account'] = old
        manager._get_account_context = AsyncMock(return_value=None)
        with self.assertRaisesRegex(ValueError, '重新扫码'):
            await manager.get_or_connect('offline-account')
        self.assertNotIn('offline-account', manager.clients)
        old.disconnect.assert_awaited_once()
        manager._get_account_context.return_value = (7, 'unb=offline-user')
        failed = SimpleNamespace(connect=AsyncMock(return_value=False), last_connect_error='注册失败')
        self.scope['GoofishImClient'] = Mock(return_value=failed)
        with self.assertRaisesRegex(RuntimeError, '注册失败'):
            await manager.get_or_connect('offline-account')
        self.assertNotIn('offline-account', manager.clients)


class CacheDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy import String, DateTime, update, select
        from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        class Base(DeclarativeBase):
            pass
        class Cache(Base):
            __tablename__ = 'xy_token_cache'
            user_id: Mapped[str] = mapped_column(String, primary_key=True)
            token: Mapped[str] = mapped_column(String)
            device_id: Mapped[str] = mapped_column(String)
            expire_at: Mapped[datetime] = mapped_column(DateTime)
            renew_expire_at: Mapped[datetime] = mapped_column(DateTime)
            updated_at: Mapped[datetime] = mapped_column(DateTime)
        self.Cache = Cache
        self.now = datetime(2026, 10, 19, 12)
        self.engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        self.addAsyncCleanup(self.engine.dispose)
        self.maker = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with self.maker() as db:
            for key in ('chat_old', 'chat_new', 'chat_other', 'old'):
                db.add(Cache(user_id=key, token='still-valid', device_id='device', expire_at=self.now + timedelta(hours=8), renew_expire_at=self.now + timedelta(hours=9), updated_at=self.now))
            await db.commit()
        self.scope = {'update': update, 'select': select, 'TokenCache': Cache, 'datetime': datetime,
                      'get_beijing_now_naive': lambda: self.now, 'trans_cookies': cookie_values,
                      'asyncio': asyncio, 'async_session_maker': self.maker,
                      'DEFAULT_DB_MAX_ATTEMPTS': 1, 'DEFAULT_DB_RETRY_DELAY_SECONDS': 0}

    async def test_fresh_login_clears_only_corresponding_chat_cache_in_transaction(self):
        load_definitions(ACCOUNT, {'_expire_chat_login_cache'}, self.scope, 'AccountService')
        async with self.maker() as db:
            await self.scope['_expire_chat_login_cache'](SimpleNamespace(session=db), SimpleNamespace(unb='old', cookie='unb=old'), 'unb=new')
            await db.commit()
            for key in ('chat_old', 'chat_new'):
                self.assertEqual((await db.get(self.Cache, key)).token, '')
            self.assertEqual((await db.get(self.Cache, 'chat_other')).token, 'still-valid')
            self.assertEqual((await db.get(self.Cache, 'old')).token, 'still-valid')

    async def test_delete_account_accepts_missing_replacement_and_empty_stored_cookies(self):
        from types import MethodType
        load_definitions('common/utils/xianyu_utils.py', {'trans_cookies'}, self.scope)
        load_definitions(ACCOUNT, {'_expire_chat_login_cache', 'delete_account'}, self.scope, 'AccountService')
        for unb, cookie in [('old', 'unb=old'), ('old', None), ('old', ''), ('old', '   '), (None, 'unb=old'), (None, None)]:
            with self.subTest(unb=unb, cookie=cookie):
                async with self.maker() as db:
                    account = SimpleNamespace(account_id='test', unb=unb, cookie=cookie)
                    session = SimpleNamespace(execute=db.execute, commit=AsyncMock(wraps=db.commit), delete=AsyncMock())
                    service = SimpleNamespace(session=session, _disconnect_chat_client=AsyncMock())
                    service._expire_chat_login_cache = MethodType(self.scope['_expire_chat_login_cache'], service)
                    await self.scope['delete_account'](service, account)
                    session.delete.assert_awaited_once_with(account)
                    session.commit.assert_awaited_once()
                    service._disconnect_chat_client.assert_awaited_once_with('test')
                    self.assertEqual((await db.get(self.Cache, 'chat_other')).token, 'still-valid')
                    self.assertEqual((await db.get(self.Cache, 'old')).token, 'still-valid')

    async def test_rejected_unexpired_token_expires_without_overwriting_replacement(self):
        @dataclass
        class Result:
            success: bool
            changed: bool = False
            message: str = ''
        self.scope['TokenCacheInvalidationResult'] = Result
        load_definitions('common/services/token_renewal_cache_service.py', {'mark_token_cache_expired'}, self.scope)
        async with self.maker() as db:
            row = await db.get(self.Cache, 'chat_old')
            row.token = 'replacement-token'
            await db.commit()
        result = await self.scope['mark_token_cache_expired'](token_user_id='chat_old', expected_token='still-valid', expected_device_id='device')
        self.assertTrue(result.success)
        self.assertFalse(result.changed)
        result = await self.scope['mark_token_cache_expired'](token_user_id='chat_other', expected_token='still-valid', expected_device_id='device')
        self.assertTrue(result.changed)
        async with self.maker() as db:
            self.assertEqual((await db.get(self.Cache, 'chat_other')).expire_at, self.now)
            self.assertEqual((await db.get(self.Cache, 'chat_old')).token, 'replacement-token')


if __name__ == '__main__':
    unittest.main()
