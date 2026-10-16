import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock

import discord
from storage import Store, normalize_email
from bot import BiggerZBot, EmailModal, LinkView


class StorageTests(unittest.TestCase):
    def test_validation(self):
        self.assertEqual(normalize_email(' Test+tag@EXAMPLE.COM '), 'Test+tag@example.com')
        for value in ['a', 'a@@example.com', 'a@localhost', 'a b@example.com', '.a@example.com', 'a..b@example.com', 'a@-example.com', 'a\n@example.com']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_email(value)

    def test_persistence_update_isolation_delete(self):
        with tempfile.TemporaryDirectory() as folder:
            path = folder + '/db.sqlite3'
            store = Store(path)
            store.save(1, 2, 'first@example.com')
            store.close()
            store = Store(path)
            self.assertEqual(store.get(1, 2)[0], 'first@example.com')
            self.assertIsNone(store.get(2, 2))
            self.assertIsNone(store.get(1, 3))
            store.save(1, 2, 'new@example.com')
            self.assertEqual(store.get(1, 2)[0], 'new@example.com')
            store.delete(1, 2)
            self.assertIsNone(store.get(1, 2))
            store.close()


class UITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        os.environ['DISCORD_GUILD_ID'] = '123456789012345678'
        os.environ['DATABASE_PATH'] = self.folder.name + '/db.sqlite3'
        self.bot = BiggerZBot()

    async def asyncTearDown(self):
        await self.bot.close()
        self.folder.cleanup()

    def interaction(self):
        i = AsyncMock()
        i.guild_id = self.bot.guild_id
        i.user.id = 42
        return i

    async def test_panels_and_persistent_buttons(self):
        view = LinkView(self.bot)
        self.assertTrue(view.is_persistent())
        self.assertEqual(len(view.to_components()[0]['components']), 3)
        self.assertLess(sum(len(e) for e in self.bot.welcome_panels), 6000)
        self.assertEqual(len(EmailModal(self.bot).to_dict()['components']), 1)
        for cmd in self.bot.tree.get_commands(guild=discord.Object(id=self.bot.guild_id)):
            self.assertTrue(cmd.default_permissions.administrator)
            self.assertTrue(cmd.checks)

    async def test_submit_private_and_delete(self):
        modal = EmailModal(self.bot)
        modal.email._value = 'member@example.com'
        i = self.interaction()
        await modal.on_submit(i)
        i.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        self.assertTrue(i.followup.send.call_args.kwargs['ephemeral'])
        self.assertEqual(self.bot.store.get(i.guild_id, 42)[0], 'member@example.com')
        await LinkView(self.bot).delete.callback(self.interaction())
        self.assertIsNone(self.bot.store.get(i.guild_id, 42))

    async def test_wrong_server_rejected(self):
        i = self.interaction()
        i.guild_id = 999
        self.assertFalse(await LinkView(self.bot).interaction_check(i))
        modal = EmailModal(self.bot)
        modal.email._value = 'member@example.com'
        await modal.on_submit(i)
        self.assertIsNone(self.bot.store.get(999, 42))

    async def test_invalid_email_not_saved(self):
        modal = EmailModal(self.bot)
        modal.email._value = 'invalid'
        i = self.interaction()
        await modal.on_submit(i)
        self.assertIsNone(self.bot.store.get(i.guild_id, 42))
        self.assertTrue(i.response.send_message.call_args.kwargs['ephemeral'])


if __name__ == '__main__':
    unittest.main()
