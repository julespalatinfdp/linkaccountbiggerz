import logging
import os

import discord
from discord import app_commands

from storage import Store, normalize_email


log = logging.getLogger("biggerz")


def required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing Railway variable: {name}")
    return value


async def report_error(interaction, error):
    # Never log email addresses or form contents.
    log.error("Interaction error: %s", type(error).__name__)

    message = (
        "Something went wrong. Please try again in a moment "
        "or contact an administrator."
    )

    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


class EmailModal(discord.ui.Modal, title="Link my BiggerZ email"):
    email = discord.ui.TextInput(
        label="Email address used on BiggerZ",
        placeholder="you@example.com",
        max_length=254,
    )

    def __init__(self, bot):
        super().__init__(timeout=300)
        self.bot = bot

    async def on_submit(self, interaction):
        if interaction.guild_id != self.bot.guild_id:
            await interaction.response.send_message(
                "This server is not authorized.",
                ephemeral=True,
            )
            return

        try:
            email = normalize_email(str(self.email))
        except ValueError:
            await interaction.response.send_message(
                "Please enter a valid email address.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        self.bot.store.save(
            interaction.guild_id,
            interaction.user.id,
            email,
        )

        await interaction.followup.send(
            "Your association is saved.",
            ephemeral=True,
        )

    async def on_error(self, interaction, error):
        await report_error(interaction, error)


class LinkView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def interaction_check(self, interaction):
        if interaction.guild_id != self.bot.guild_id:
            await interaction.response.send_message(
                "This server is not authorized.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Add / update my account",
        emoji="🔗",
        style=discord.ButtonStyle.primary,
        custom_id="biggerz:link:v1",
    )
    async def link(self, interaction, button):
        await interaction.response.send_modal(EmailModal(self.bot))

    @discord.ui.button(
        label="View my email",
        emoji="👁️",
        style=discord.ButtonStyle.secondary,
        custom_id="biggerz:view:v1",
    )
    async def view_email(self, interaction, button):
        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        row = self.bot.store.get(
            interaction.guild_id,
            interaction.user.id,
        )

        if row:
            message = (
                "Your registered email: "
                + discord.utils.escape_markdown(row[0])
            )
        else:
            message = "You haven’t registered an email address yet."

        await interaction.followup.send(
            message,
            ephemeral=True,
        )

    @discord.ui.button(
        label="Remove my association",
        emoji="🗑️",
        style=discord.ButtonStyle.danger,
        custom_id="biggerz:delete:v1",
    )
    async def delete(self, interaction, button):
        await interaction.response.defer(
            ephemeral=True,
            thinking=True,
        )

        self.bot.store.delete(
            interaction.guild_id,
            interaction.user.id,
        )

        await interaction.followup.send(
            "Your association and email address have been "
            "removed from the bot’s active database.",
            ephemeral=True,
        )

    async def on_error(self, interaction, error, item):
        await report_error(interaction, error)


def panels():
    welcome = discord.Embed(
        title="Welcome to the BiggerZ server!",
        description=(
            "BiggerZ is your home for **Casino**, **Sportsbook** and "
            "**Prediction Markets**\n\n"
            "**Join thousands of players, share your biggest wins, "
            "discuss betting strategies, discover new opportunities, "
            "and participate in exclusive community rewards.**"
        ),
        color=0x7856FF,
    )

    welcome.add_field(
        name="Your BiggerZ account",
        value=(
            "You can register your account’s email address using the form below. "
            "This is VERY IMPORTANT because it allows you to win exclusive "
            "community gifts, complete all "
            "[quests](https://discord.com/channels/"
            "1517592147467960393/1559585588896600125) "
            "and access VIP channels if you’re eligible."
        ),
        inline=False,
    )

    link = discord.Embed(
        title="Add your BiggerZ account",
        description=(
            "Link your Discord account to the email address you use on BiggerZ."
            "\n\n"
            "Click “Add / update my account”.\n"
            "Enter your BiggerZ email address in the private form.\n"
            "Your association is saved."
        ),
        color=0x7856FF,
    )

    return [welcome, link]


class BiggerZBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.none()
        intents.guilds = True

        super().__init__(
            intents=intents,
            allowed_mentions=discord.AllowedMentions.none(),
        )

        self.guild_id = int(required("DISCORD_GUILD_ID"))

        self.store = Store(
            os.environ.get(
                "DATABASE_PATH",
                "/data/biggerz.sqlite3",
            )
        )

        self.tree = app_commands.CommandTree(self)
        self.welcome_panels = panels()

        guild = discord.Object(id=self.guild_id)

        @self.tree.command(
            name="installer",
            description="Publish the BiggerZ panels in this channel",
            guild=guild,
        )
        @app_commands.default_permissions(administrator=True)
        @app_commands.checks.has_permissions(administrator=True)
        async def install(interaction: discord.Interaction):
            await interaction.response.defer(
                ephemeral=True,
                thinking=True,
            )

            await interaction.channel.send(
                embeds=self.welcome_panels,
                view=LinkView(self),
            )

            await interaction.followup.send(
                "Panels published. You can pin the message. "
                "Running this command again publishes a new message.",
                ephemeral=True,
            )

        @self.tree.command(
            name="compte",
            description="View a member’s declared email (administrators only)",
            guild=guild,
        )
        @app_commands.default_permissions(administrator=True)
        @app_commands.checks.has_permissions(administrator=True)
        async def account(
            interaction: discord.Interaction,
            membre: discord.Member,
        ):
            await interaction.response.defer(
                ephemeral=True,
                thinking=True,
            )

            row = self.store.get(
                interaction.guild_id,
                membre.id,
            )

            if row:
                message = (
                    "Declared email: "
                    + discord.utils.escape_markdown(row[0])
                    + "\nLast updated (UTC): "
                    + row[1]
                    + "\nStatus: not verified."
                )
            else:
                message = "No association registered for this member."

            await interaction.followup.send(
                message,
                ephemeral=True,
            )

        @self.tree.error
        async def command_error(interaction, error):
            if isinstance(error, app_commands.CheckFailure):
                await interaction.response.send_message(
                    "This command is restricted to administrators.",
                    ephemeral=True,
                )
            else:
                await report_error(interaction, error)

    async def setup_hook(self):
        self.add_view(LinkView(self))

        await self.tree.sync(
            guild=discord.Object(id=self.guild_id)
        )

    async def on_ready(self):
        log.info(
            "Bot connected. Publish the panels with /installer."
        )

    async def close(self):
        await super().close()
        self.store.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    os.umask(0o077)

    token = required("DISCORD_TOKEN")
    bot = BiggerZBot()

    bot.run(
        token,
        log_level=logging.WARNING,
    )
