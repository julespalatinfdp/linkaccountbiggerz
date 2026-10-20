import asyncio
import logging
import os
import time
from urllib.parse import quote

import discord
from discord import app_commands
from discord.ext import tasks

from biggerz import APIError, BiggerZ, expiry
from storage import Store

log = logging.getLogger('biggerz')


def required(name):
    value = os.environ.get(name, '').strip()
    if not value:
        raise RuntimeError(f'Missing Railway variable: {name}')
    return value


async def reply(interaction, message, view=None):
    kwargs = {'content': message}
    if view is not None:
        kwargs['view'] = view
    if interaction.response.is_done():
        await interaction.edit_original_response(**kwargs)
    else:
        await interaction.response.send_message(**kwargs, ephemeral=True)


async def report_error(interaction, error):
    # Never log URLs, secrets, response bodies or user input.
    log.warning('Operation failed: %s', type(error).__name__)
    message = 'BiggerZ is temporarily unavailable. Please try again shortly.'
    if isinstance(error, APIError) and error.status == 429:
        message = 'Too many requests. Please wait a few minutes before trying again.'
    await reply(interaction, message)


class Panel(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def interaction_check(self, interaction):
        if interaction.guild_id != self.bot.guild_id:
            await reply(interaction, 'This server is not authorized.')
            return False
        return True

    # Keep previous IDs so already published buttons still reach the new bot.
    @discord.ui.button(label='Link / update my account', emoji='🔗', style=discord.ButtonStyle.primary, custom_id='biggerz:link:v1')
    async def link(self, interaction, button):
        await self.bot.link_account(interaction)

    @discord.ui.button(label='View my account', emoji='👁️', custom_id='biggerz:view:v1')
    async def account(self, interaction, button):
        await self.bot.view_account(interaction)

    @discord.ui.button(label='Unlink my account', emoji='🗑️', style=discord.ButtonStyle.danger, custom_id='biggerz:delete:v1')
    async def unlink(self, interaction, button):
        await self.bot.ask_unlink(interaction)

    async def on_error(self, interaction, error, item):
        await report_error(interaction, error)


class ConfirmUnlink(discord.ui.View):
    def __init__(self, bot, owner):
        super().__init__(timeout=60)
        self.bot, self.owner = bot, owner

    async def interaction_check(self, interaction):
        return interaction.user.id == self.owner and interaction.guild_id == self.bot.guild_id

    @discord.ui.button(label='Confirm unlink', style=discord.ButtonStyle.danger)
    async def confirm(self, interaction, button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            async with self.bot.user_lock(str(self.owner)):
                # The API does not document a pending-request cancellation endpoint.
                # Avoid deleting a link while a known request could recreate it.
                for uid, rid, until in self.bot.store.pending():
                    if uid == str(self.owner) and expiry(until) > time.time():
                        state = await self.bot.api.request('GET', '/link-requests/' + quote(rid, safe=''), deadline=expiry(until))
                        if state.get('status') == 'pending':
                            await reply(interaction, 'A linking request is still pending. Cancel it on BiggerZ or wait for it to expire, then unlink.')
                            return
                        self.bot.store.end_pending(uid, rid)
                try:
                    await self.bot.api.request('DELETE', '/links/' + str(self.owner))
                except APIError as error:
                    if not (error.status == 404 and error.code == 'not_linked'):
                        raise
            await reply(interaction, 'Your BiggerZ account has been unlinked.', discord.ui.View())
            self.stop()
        except Exception as error:
            await report_error(interaction, error)


def panels():
    welcome = discord.Embed(
        title='Welcome to the BiggerZ server!', color=0xF5C451,
        description=(
            'BiggerZ is your home for **Casino**, **Sportsbook** and **Prediction Markets**\n\n'
            '**Join thousands of players, share your biggest wins, discuss betting strategies, '
            'discover new opportunities, and participate in exclusive community rewards.**'))
    welcome.add_field(name='Your BiggerZ account', inline=False, value=(
        'You can link your BiggerZ account using the button below.\n\n'
        'This is **VERY IMPORTANT** because it allows you to:\n\n'
        '• Win **exclusive community gifts**\n'
        '• Complete all [**quests**](https://discord.com/channels/1517592147467960393/1559585588896600125)\n'
        '• Access **VIP channels** if you’re eligible.'))
    banner = os.environ.get('BANNER_URL', (
        'https://cdn.discordapp.com/attachments/1559585707742208090/'
        '1560563024409001994/visual-4dc51277-1a49-43ba-865e-10550f51fcc4.png'
        '?ex=6ad3d3d2&is=6ad28252'
        '&hm=a251fda6b5e6dcf0936a21527dae921fd57b4aaca095baff47bd4fda9ad3714e'
    )).strip()
    if banner:
        if not banner.startswith('https://'):
            raise RuntimeError('BANNER_URL must be an HTTPS image URL.')
        welcome.set_image(url=banner)
    link = discord.Embed(title='Link your BiggerZ account', color=0xF5C451, description=(
        'Connect your Discord account to your BiggerZ account.\n\n'
        '**1️⃣  Click “Link / update my account”.**\n\n'
        '**2️⃣  Open your private link, sign in to BiggerZ and click “Confirm”.**\n\n'
        '**3️⃣  Your account is linked.**'))
    return [welcome, link]


class Bot(discord.Client):
    def __init__(self):
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.guild_id = int(required('DISCORD_GUILD_ID'))
        self.api = BiggerZ(required('BIGGERZ_API_BASE_URL'), required('BIGGERZ_API_KEY'))
        self.store = Store(os.environ.get('DATABASE_PATH', '/data/biggerz-staging.sqlite3'), self.api.base)
        self.tree = app_commands.CommandTree(self)
        self.locks, self.notifications = {}, {}
        self.embeds = panels()
        guild = discord.Object(id=self.guild_id)

        @self.tree.command(name='installer', description='Publish the BiggerZ welcome panels', guild=guild)
        @app_commands.default_permissions(administrator=True)
        @app_commands.checks.has_permissions(administrator=True)
        async def install(i: discord.Interaction):
            await i.response.defer(ephemeral=True, thinking=True)
            await i.channel.send(embeds=self.embeds, view=Panel(self))
            await reply(i, 'Panels published. You can pin the message.')

        @self.tree.command(name='link', description='Link your BiggerZ account', guild=guild)
        async def link(i: discord.Interaction):
            await self.link_account(i)

        @self.tree.command(name='account', description='Check your BiggerZ account link', guild=guild)
        async def account(i: discord.Interaction):
            await self.view_account(i)

        @self.tree.command(name='unlink', description='Remove your BiggerZ account link', guild=guild)
        async def unlink(i: discord.Interaction):
            await self.ask_unlink(i)

        @self.tree.command(name='compte', description='Check a member’s linked account (administrators)', guild=guild)
        @app_commands.default_permissions(administrator=True)
        @app_commands.checks.has_permissions(administrator=True)
        async def lookup(i: discord.Interaction, membre: discord.Member):
            await self.view_account(i, str(membre.id))

        @self.tree.error
        async def on_error(i, error):
            if isinstance(error, app_commands.CheckFailure):
                await reply(i, 'This command is restricted to administrators.')
            else:
                await report_error(i, getattr(error, 'original', error))

    def user_lock(self, uid):
        return self.locks.setdefault(uid, asyncio.Lock())

    async def allowed(self, i):
        if i.guild_id != self.guild_id:
            await reply(i, 'This server is not authorized.')
            return False
        return True

    async def link_account(self, i):
        if not await self.allowed(i):
            return
        await i.response.defer(ephemeral=True, thinking=True)
        uid = str(i.user.id)
        async with self.user_lock(uid):
            # Avoid accidental double-clicks consuming five requests per ten minutes.
            for owner, rid, until in self.store.pending():
                if owner == uid and expiry(until) > time.time():
                    await reply(i, 'You already have a pending request. Use the private link previously sent to you, or wait up to 15 minutes for it to expire. Use /account to check your link.')
                    return
            data = await self.api.request('POST', '/link-requests', {
                'discord_id': uid, 'discord_username': i.user.name,
            })
            if (data.get('discord_id') != uid or data.get('status') != 'pending'
                    or not isinstance(data.get('id'), str)
                    or not self.api.valid_link(data.get('link_url', ''))):
                raise RuntimeError('Unexpected link response')
            if expiry(data['expires_at']) <= time.time():
                raise RuntimeError('Expired link response')
            self.store.put_pending(uid, data['id'], data['expires_at'])
            self.notifications[data['id']] = i
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label='Confirm on BiggerZ', style=discord.ButtonStyle.link, url=data['link_url']))
            await reply(i, 'Open your private link, sign in to BiggerZ and click **Confirm**.\nThis link expires in 15 minutes. Keep it private.\nUse **/account** to check your account at any time.', view)

    async def view_account(self, i, uid=None):
        if not await self.allowed(i):
            return
        await i.response.defer(ephemeral=True, thinking=True)
        uid = uid or str(i.user.id)
        try:
            data = await self.api.request('GET', '/links/' + uid)
        except APIError as error:
            if error.status == 404 and error.code == 'not_linked':
                await reply(i, 'No BiggerZ account is currently linked. Click “Link / update my account” to get started.')
                return
            raise
        if data.get('discord_id') != uid or not isinstance(data.get('biggerz_user_id'), str):
            raise RuntimeError('Invalid account response')
        await reply(i, '✅ **Account linked**\nBiggerZ ID: ' + discord.utils.escape_markdown(data['biggerz_user_id']))

    async def ask_unlink(self, i):
        if await self.allowed(i):
            await reply(i, 'Remove the connection between your Discord and BiggerZ accounts?', ConfirmUnlink(self, i.user.id))

    async def finish_request(self, uid, rid, status):
        self.store.end_pending(uid, rid)
        i = self.notifications.pop(rid, None)
        messages = {
            'confirmed': '✅ Your linking request was confirmed. Use **/account** to see your current linked account.',
            'cancelled': 'Your linking request was cancelled. You can create a new one.',
            'expired': 'Your linking request has expired. Click “Link / update my account” to create a new one.',
        }
        if i:
            try:
                await reply(i, messages.get(status, 'This request is no longer pending. Use /account to check your account.'), discord.ui.View())
            except discord.HTTPException:
                pass  # Ephemeral interaction tokens expire; /account remains available.

    @tasks.loop(seconds=4)
    async def poll_pending(self):
        for uid, rid, until in self.store.pending():
            try:
                async with self.user_lock(uid):
                    if expiry(until) <= time.time():
                        await self.finish_request(uid, rid, 'expired')
                        continue
                    data = await self.api.request('GET', '/link-requests/' + quote(rid, safe=''), deadline=expiry(until))
                    if data.get('discord_id') != uid or data.get('id') != rid:
                        raise RuntimeError('Invalid polling response')
                    status = data.get('status', 'unknown')
                    if status != 'pending':
                        await self.finish_request(uid, rid, status)
            except APIError as error:
                if error.status in (404, 408):
                    await self.finish_request(uid, rid, 'expired')
                else:
                    log.warning('Pending sync: HTTP %s', error.status)
                    break
            except Exception as error:
                log.warning('Pending sync: %s', type(error).__name__)

    @tasks.loop(seconds=60)
    async def sync_events(self):
        try:
            while True:
                params = {'limit': 500}
                cursor = self.store.cursor()
                if cursor:
                    params['after'] = cursor
                page = await self.api.request('GET', '/events', params=params)
                if not isinstance(page.get('events'), list):
                    raise RuntimeError('Invalid events response')
                if page['events'] and (not page.get('next_cursor') or page['next_cursor'] == cursor):
                    raise RuntimeError('Events cursor did not advance')
                self.store.apply_page(page)
                if len(page['events']) < 500:
                    break
        except Exception as error:
            log.warning('Event sync: %s', type(error).__name__)

    @poll_pending.before_loop
    @sync_events.before_loop
    async def wait_ready(self):
        await self.wait_until_ready()

    async def setup_hook(self):
        await self.api.start()
        self.add_view(Panel(self))
        await self.tree.sync(guild=discord.Object(id=self.guild_id))
        self.poll_pending.start()
        self.sync_events.start()

    async def on_ready(self):
        log.info('Connected. Use /installer to publish the welcome panels.')

    async def close(self):
        jobs = [job.get_task() for job in (self.poll_pending, self.sync_events) if job.get_task()]
        for job in (self.poll_pending, self.sync_events):
            job.cancel()
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)
        await self.api.close()
        await super().close()
        self.store.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    os.umask(0o077)
    token = required('DISCORD_TOKEN')
    Bot().run(token, log_level=logging.WARNING)
