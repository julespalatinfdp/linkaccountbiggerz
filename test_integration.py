import os
import tempfile
import time
import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

from biggerz import APIError, BiggerZ
from bot import Bot, Panel, ConfirmUnlink
from storage import Store

BASE = 'https://v2biggerz.live/nitro/integrations/discord/v1'


def future():
    return (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()


def event(kind, discord='d1', biggerz='b1', **extra):
    return {'type': kind, 'discord_id': discord, 'biggerz_user_id': biggerz, **extra}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = self.temp.name + '/store.sqlite3'
        self.store = Store(self.path, BASE)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def links(self):
        return self.store.db.execute('SELECT * FROM verified_links ORDER BY discord_id').fetchall()

    def test_restart_preserves_cursor_and_pending(self):
        self.store.put_pending('d', 'lr', future())
        self.store.apply_page({'events': [event('link.created')], 'next_cursor': 'c1'})
        self.store.close()
        self.store = Store(self.path, BASE)
        self.assertEqual(self.store.cursor(), 'c1')
        self.assertEqual(self.store.pending()[0][1], 'lr')
        self.assertEqual(self.links(), [('d1', 'b1')])

    def test_idempotence_and_pair_specific_deletion(self):
        page = {'events': [event('link.created'), event('link.created', biggerz='b2'),
                           event('link.removed', reason='future_reason')], 'next_cursor': 'c2'}
        self.store.apply_page(page)
        self.store.apply_page(page)
        self.assertEqual(self.links(), [('d1', 'b2')])
        self.store.apply_page({'events': [event('link.removed', biggerz='b2', reason='unlinked_by_admin')], 'next_cursor': 'c3'})
        self.assertEqual(self.links(), [])

    def test_one_to_one(self):
        self.store.apply_page({'events': [event('link.created'), event('link.created', discord='d2')], 'next_cursor': 'c'})
        self.assertEqual(self.links(), [('d2', 'b1')])

    def test_page_rolls_back_on_invalid_event(self):
        with self.assertRaises(ValueError):
            self.store.apply_page({'events': [event('link.created'), event('link.created', discord=123)], 'next_cursor': 'bad'})
        self.assertIsNone(self.store.cursor())
        self.assertEqual(self.links(), [])

    def test_unknown_event_and_reason(self):
        self.store.apply_page({'events': [event('future.type'), event('link.created', reason='new')], 'next_cursor': 'c'})
        self.assertEqual(self.links(), [('d1', 'b1')])

    def test_old_request_cannot_remove_new_pending(self):
        self.store.put_pending('d', 'new', future())
        self.store.end_pending('d', 'old')
        self.assertEqual(self.store.pending()[0][1], 'new')


class BotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            'DISCORD_GUILD_ID': '123456789012345678', 'BIGGERZ_API_BASE_URL': BASE,
            'BIGGERZ_API_KEY': 'test-placeholder', 'DATABASE_PATH': self.temp.name + '/db.sqlite3',
        })
        self.env.start()
        self.bot = Bot()
        self.bot.api.request = AsyncMock()

    async def asyncTearDown(self):
        await self.bot.close()
        self.env.stop()
        self.temp.cleanup()

    def interaction(self):
        i = SimpleNamespace(guild_id=self.bot.guild_id, user=SimpleNamespace(id=456, name='member'),
                            response=SimpleNamespace(defer=AsyncMock(), is_done=lambda: True),
                            edit_original_response=AsyncMock())
        return i

    async def test_private_link_and_duplicate_click(self):
        self.bot.api.request.return_value = {
            'id': 'lr1', 'discord_id': '456', 'status': 'pending', 'expires_at': future(),
            'link_url': 'https://v2biggerz.live/link/discord?token=private-test',
        }
        i = self.interaction()
        await self.bot.link_account(i)
        i.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        self.assertEqual(i.edit_original_response.call_args.kwargs['view'].children[0].url,
                         'https://v2biggerz.live/link/discord?token=private-test')
        await self.bot.link_account(self.interaction())
        self.assertEqual(self.bot.api.request.await_count, 1)
        # Private token is not stored in the database.
        self.assertNotIn('private-test', self.bot.store.db.iterdump().__str__())
        self.assertNotIn('private-test', '\n'.join(self.bot.store.db.iterdump()))

    async def test_expired_request_not_polled(self):
        self.bot.store.put_pending('456', 'lr', '2000-01-01T00:00:00Z')
        await self.bot.poll_pending()
        self.bot.api.request.assert_not_awaited()
        self.assertEqual(self.bot.store.pending(), [])

    async def test_confirmed_stops_polling(self):
        self.bot.store.put_pending('456', 'lr', future())
        self.bot.api.request.return_value = {'id': 'lr', 'discord_id': '456', 'status': 'confirmed', 'biggerz_user_id': 'bz'}
        await self.bot.poll_pending()
        await self.bot.poll_pending()
        self.assertEqual(self.bot.api.request.await_count, 1)

    async def test_full_event_page_drained(self):
        self.bot.api.request.side_effect = [
            {'events': [event('link.created')] * 500, 'next_cursor': 'c1'},
            {'events': [event('link.removed')], 'next_cursor': 'c2'},
        ]
        await self.bot.sync_events()
        self.assertEqual(self.bot.store.cursor(), 'c2')
        self.assertEqual(self.bot.api.request.await_args_list[1].kwargs['params']['after'], 'c1')

    async def test_delete_not_linked_is_success(self):
        self.bot.api.request.side_effect = APIError(404, 'not_linked')
        i = self.interaction()
        view = ConfirmUnlink(self.bot, 456)
        await view.confirm.callback(i)
        self.assertIn('has been unlinked', i.edit_original_response.call_args.kwargs['content'])

    async def test_pending_blocks_unlink(self):
        self.bot.store.put_pending('456', 'lr', future())
        self.bot.api.request.return_value = {'status': 'pending'}
        i = self.interaction()
        await ConfirmUnlink(self.bot, 456).confirm.callback(i)
        self.assertEqual(self.bot.api.request.await_args.args[0], 'GET')
        self.assertIn('still pending', i.edit_original_response.call_args.kwargs['content'])

    async def test_views_and_admin_protection(self):
        self.assertTrue(Panel(self.bot).is_persistent())
        guild = discord.Object(id=self.bot.guild_id)
        for command in self.bot.tree.get_commands(guild=guild):
            if command.name in ('installer', 'compte'):
                self.assertTrue(command.default_permissions.administrator)
                self.assertTrue(command.checks)
        self.assertLess(sum(len(e) for e in self.bot.embeds), 6000)


class FakeResponse:
    def __init__(self, status, data, headers=None):
        self.status, self.data, self.headers = status, data, headers or {}
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    async def json(self, **kwargs):
        return self.data


class APITests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_429_sets_global_cooldown(self):
        api = BiggerZ(BASE, 'placeholder')
        calls = []
        responses = iter([FakeResponse(429, {'error': {'code': 'rate_limited'}}, {'Retry-After': '7'}), FakeResponse(200, {'ok': True})])
        def request(*args, **kwargs):
            calls.append(kwargs)
            return next(responses)
        api.session = SimpleNamespace(request=request)
        with patch('biggerz.asyncio.sleep', new_callable=AsyncMock) as sleep:
            result = await api.request('GET', '/events')
            self.assertTrue(result['ok'])
            self.assertGreater(api.cooldown, time.monotonic())
            self.assertTrue(any(call.args[0] > 6 for call in sleep.await_args_list))
        self.assertFalse(calls[0]['allow_redirects'])

    async def test_expired_deadline_prevents_network(self):
        api = BiggerZ(BASE, 'placeholder')
        with self.assertRaises(APIError):
            await api.request('GET', '/events', deadline=time.time() - 1)

    async def test_link_host_validation(self):
        api = BiggerZ(BASE, 'placeholder')
        self.assertTrue(api.valid_link('https://v2biggerz.live/link/discord?token=x'))
        self.assertFalse(api.valid_link('https://v2biggerz.live.evil.test/link/discord?token=x'))
        self.assertFalse(api.valid_link('https://www.biggerz.com/link/discord?token=x'))

    async def test_401_not_retried(self):
        from unittest.mock import Mock
        api = BiggerZ(BASE, 'placeholder')
        request = Mock(return_value=FakeResponse(401, {'error': {'code': 'unauthorized'}}))
        api.session = SimpleNamespace(request=request)
        with self.assertRaises(APIError):
            await api.request('GET', '/events')
        self.assertEqual(request.call_count, 1)


if __name__ == '__main__':
    unittest.main()
