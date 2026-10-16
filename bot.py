import logging
import os

import discord
from discord import app_commands
from storage import Store, normalize_email

log = logging.getLogger('biggerz')


def required(name):
    value = os.environ.get(name, '').strip()
    if not value:
        raise RuntimeError(f'Variable Railway manquante : {name}')
    return value


class EmailModal(discord.ui.Modal, title='Associer mon e-mail BiggerZ'):
    email = discord.ui.TextInput(label='E-mail utilisé sur BiggerZ', placeholder='toi@exemple.com', max_length=254)

    def __init__(self, bot):
        super().__init__(timeout=300)
        self.bot = bot

    async def on_submit(self, interaction):
        if interaction.guild_id != self.bot.guild_id:
            return await interaction.response.send_message('Serveur non autorisé.', ephemeral=True)
        try:
            email = normalize_email(str(self.email))
        except ValueError:
            return await interaction.response.send_message('Adresse invalide. Recommence avec une adresse e-mail complète.', ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        self.bot.store.save(interaction.guild_id, interaction.user.id, email)
        await interaction.followup.send(
            '✅ Ton e-mail a été enregistré et associé à ton compte Discord.\n'
            'Cette association est déclarative : elle ne vérifie ni la propriété de l’adresse ni l’existence du compte BiggerZ.\n'
            'Tu peux la modifier ou la supprimer avec les boutons.', ephemeral=True)

    async def on_error(self, interaction, error):
        await report_error(interaction, error)


async def report_error(interaction, error):
    # Ne pas journaliser les valeurs du formulaire ni le contenu des exceptions.
    log.error('Erreur interaction : %s', type(error).__name__)
    message = 'Une erreur est survenue. Réessaie dans quelques instants ou contacte un administrateur.'
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


class LinkView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def interaction_check(self, interaction):
        if interaction.guild_id != self.bot.guild_id:
            await interaction.response.send_message('Serveur non autorisé.', ephemeral=True)
            return False
        return True

    @discord.ui.button(label='Ajouter / modifier mon compte', emoji='🔗', style=discord.ButtonStyle.primary, custom_id='biggerz:link:v1')
    async def link(self, interaction, button):
        await interaction.response.send_modal(EmailModal(self.bot))

    @discord.ui.button(label='Voir mon e-mail', emoji='👁️', style=discord.ButtonStyle.secondary, custom_id='biggerz:view:v1')
    async def view_email(self, interaction, button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        row = self.bot.store.get(interaction.guild_id, interaction.user.id)
        message = ('E-mail déclaré : ' + discord.utils.escape_markdown(row[0]) + '\nStatut : non vérifié.') if row else 'Tu n’as pas encore enregistré d’e-mail.'
        await interaction.followup.send(message, ephemeral=True)

    @discord.ui.button(label='Supprimer mon association', emoji='🗑️', style=discord.ButtonStyle.danger, custom_id='biggerz:delete:v1')
    async def delete(self, interaction, button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        self.bot.store.delete(interaction.guild_id, interaction.user.id)
        await interaction.followup.send('Ton association et ton e-mail ont été supprimés de la base active du bot.', ephemeral=True)

    async def on_error(self, interaction, error, item):
        await report_error(interaction, error)


def panels():
    description = os.environ.get('SERVER_DESCRIPTION',
        'Le serveur de la communauté BiggerZ : échange avec les membres, retrouve les annonces et découvre les informations utiles.')
    if len(description) > 2500:
        raise RuntimeError('SERVER_DESCRIPTION doit contenir au maximum 2500 caractères.')
    welcome = discord.Embed(title='👋 Bienvenue sur le serveur BiggerZ !', description=description, color=0x7856FF)
    channels = []
    for name, label in [('RULES_CHANNEL_ID', 'Règlement'), ('GUIDE_CHANNEL_ID', 'Guide du serveur')]:
        value = os.environ.get(name, '').strip()
        if value:
            if not value.isdigit():
                raise RuntimeError(f'{name} doit être un identifiant Discord numérique.')
            channels.append(f'• <#{value}> — {label}')
    if channels:
        welcome.add_field(name='Les salons à consulter', value='\n'.join(channels), inline=False)
    welcome.add_field(name='Ton compte BiggerZ', value='Tu peux enregistrer l’e-mail de ton compte via le formulaire ci-dessous. Ne publie pas ton adresse dans le salon.', inline=False)
    for name, setter in [('LOGO_URL', welcome.set_thumbnail), ('BANNER_URL', welcome.set_image)]:
        url = os.environ.get(name, '').strip()
        if url:
            if not url.startswith('https://'):
                raise RuntimeError(f'{name} doit commencer par https://')
            setter(url=url)
    link = discord.Embed(title='🔗 Ajoute ton compte BiggerZ', description=
        'Associe ton compte Discord à l’e-mail que tu utilises sur BiggerZ.\n\n'
        '**1️⃣** Clique sur « Ajouter / modifier mon compte ».\n'
        '**2️⃣** Renseigne ton e-mail BiggerZ dans le formulaire privé.\n'
        '**3️⃣** Ton association déclarée est enregistrée.\n\n'
        'Aucun mot de passe ni code de connexion ne sera demandé. '
        'Cette saisie ne constitue pas une vérification du compte BiggerZ.', color=0x7856FF)
    link.add_field(name='Tes données', value=
        'En envoyant le formulaire, tu demandes l’enregistrement de ton identifiant Discord et de ton e-mail '
        'pour gérer ton association. Ton e-mail n’est pas publié dans le salon. '
        'Les administrateurs du serveur peuvent le consulter. Tu peux le supprimer avec le bouton dédié.', inline=False)
    link.set_footer(text='Association déclarative • Modification et suppression à tout moment')
    return [welcome, link]


class BiggerZBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.guild_id = int(required('DISCORD_GUILD_ID'))
        self.store = Store(os.environ.get('DATABASE_PATH', '/data/biggerz.sqlite3'))
        self.tree = app_commands.CommandTree(self)
        self.welcome_panels = panels()
        guild = discord.Object(id=self.guild_id)

        @self.tree.command(name='installer', description='Publier les panneaux BiggerZ dans ce salon', guild=guild)
        @app_commands.default_permissions(administrator=True)
        @app_commands.checks.has_permissions(administrator=True)
        async def install(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True, thinking=True)
            await interaction.channel.send(embeds=self.welcome_panels, view=LinkView(self))
            await interaction.followup.send('✅ Panneaux publiés. Tu peux épingler le message. Relancer cette commande publie un nouveau message.', ephemeral=True)

        @self.tree.command(name='compte', description='Consulter l’e-mail déclaré par un membre (administration)', guild=guild)
        @app_commands.default_permissions(administrator=True)
        @app_commands.checks.has_permissions(administrator=True)
        async def account(interaction: discord.Interaction, membre: discord.Member):
            await interaction.response.defer(ephemeral=True, thinking=True)
            row = self.store.get(interaction.guild_id, membre.id)
            message = ('E-mail déclaré : ' + discord.utils.escape_markdown(row[0]) + '\nDernière modification (UTC) : ' + row[1] + '\nStatut : non vérifié.') if row else 'Aucune association enregistrée pour ce membre.'
            await interaction.followup.send(message, ephemeral=True)

        @self.tree.error
        async def command_error(interaction, error):
            if isinstance(error, app_commands.CheckFailure):
                await interaction.response.send_message('Commande réservée aux administrateurs.', ephemeral=True)
            else:
                await report_error(interaction, error)

    async def setup_hook(self):
        self.add_view(LinkView(self))
        await self.tree.sync(guild=discord.Object(id=self.guild_id))

    async def on_ready(self):
        log.info('Bot connecté ; panneaux disponibles avec /installer.')

    async def close(self):
        await super().close()
        self.store.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    os.umask(0o077)
    token = required('DISCORD_TOKEN')
    bot = BiggerZBot()
    bot.run(token, log_level=logging.WARNING)
