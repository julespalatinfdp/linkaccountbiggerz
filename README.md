# Bot Discord BiggerZ — GitHub + Railway

Un message d’accueil et un panneau d’association inspirés des captures fournies, en français. Les boutons restent utilisables après un redémarrage du bot.

**Périmètre : association déclarative Discord ↔ e-mail.** Ce projet ne se connecte pas au système de comptes BiggerZ et ne vérifie pas que l’adresse appartient au membre ou à un compte BiggerZ. Aucune attribution de récompense, aucun paiement et aucun rôle « vérifié » ne sont automatisés. Une véritable liaison nécessite une API ou un OAuth officiel fourni par BiggerZ. Un code envoyé par e-mail vérifierait la boîte mail, pas à lui seul le compte BiggerZ.

## 1. Créer l’application Discord

1. Ouvre https://discord.com/developers/applications et crée une application appelée **BiggerZ** (avec l’accord du client pour son identité visuelle).
2. Dans **Bot**, crée/récupère le bot, puis copie son token avec **Reset Token** si nécessaire. Ce token va uniquement dans Railway, jamais dans GitHub ou un message Discord.
3. Les options privilégiées **Message Content**, **Server Members** et **Presence** ne sont pas nécessaires : laisse-les désactivées.
4. Dans **OAuth2 → URL Generator**, sélectionne `bot` et `applications.commands`. Accorde au bot **View Channels**, **Send Messages** et **Embed Links**. Ouvre l’URL et ajoute le bot au serveur. Il n’a pas besoin de la permission Administrateur.
5. Dans Discord, active **Paramètres utilisateur → Avancés → Mode développeur**. Clic droit sur le serveur → **Copier l’identifiant du serveur**. Fais de même sur les salons de règlement et de guide si tu souhaites les afficher.
6. Laisse **Interactions Endpoint URL** vide : ce bot reçoit les interactions via la connexion Gateway.

## 2. Mettre le code sur GitHub

Décompresse l’archive. Crée un dépôt GitHub, puis utilise **Add file → Upload files** pour y déposer le CONTENU du dossier `biggerz-discord-bot` et valider le commit.

`Dockerfile`, `bot.py`, `storage.py`, `requirements.txt` et `railway.toml` doivent être à la racine du dépôt. Ajoute aussi le guide, les tests et les fichiers cachés `.gitignore`, `.dockerignore`, `.env.example` (via Git si ton sélecteur les masque). Ne mets aucun vrai token ni base de données dans le dépôt.

## 3. Déployer sur Railway

1. **New Project → Deploy from GitHub repo**, sélectionne ce dépôt. Railway utilise le `Dockerfile` et lance `python bot.py`.
2. Dans le service du bot, ajoute les variables ci-dessous. Un premier déploiement sans variables peut échouer : redéploie après configuration.
3. Ajoute un **Volume** au service et choisis exactement **`/data`** comme chemin de montage. Il conserve la base SQLite lors des redéploiements. Sans ce volume, les associations peuvent disparaître.
4. Garde **une seule instance/réplique**. Désactive le mode de mise en veille / Serverless s’il est proposé : le bot doit conserver sa connexion Discord en continu. Aucun domaine public, port HTTP ni healthcheck HTTP n’est nécessaire.
5. Déploie. Les logs doivent afficher **Bot connecté ; panneaux disponibles avec /installer.**
6. Dans le salon d’accueil de Discord, un administrateur du serveur exécute **`/installer`**. Le bot publie un seul message contenant les deux panneaux et les trois boutons. Épingle-le si souhaité.

Chaque appel à `/installer` publie un nouveau message. Supprime l’ancien message si tu remplaces le panneau. Les panneaux ne sont pas renvoyés à chaque redémarrage et aucun message privé automatique n’est envoyé aux nouveaux membres.

## Variables Railway

| Variable | Valeur / rôle | Obligatoire |
|---|---|---|
| `DISCORD_TOKEN` | Token du bot depuis le Developer Portal | Oui |
| `DISCORD_GUILD_ID` | Identifiant numérique de ton serveur Discord | Oui |
| `DATABASE_PATH` | `/data/biggerz.sqlite3` | À définir ainsi avec le volume `/data` |
| `RULES_CHANNEL_ID` | Identifiant du salon règlement | Non |
| `GUIDE_CHANNEL_ID` | Identifiant du salon guide | Non |
| `LOGO_URL` | URL HTTPS publique directe vers le logo autorisé par BiggerZ | Non |
| `BANNER_URL` | URL HTTPS publique directe vers la bannière | Non |
| `SERVER_DESCRIPTION` | Description de ton serveur, au maximum 2 500 caractères | Non |

Le fichier `.env.example` contient le modèle à recopier dans les variables Railway. Les valeurs `COLLER_...` doivent être remplacées. Aucun fichier `.env` n’est lu automatiquement par Python. Railway injecte directement les variables.

Description par défaut :
> Le serveur de la communauté BiggerZ : échange avec les membres, retrouve les annonces et découvre les informations utiles.

Pour changer les textes détaillés, édite la fonction `panels()` de `bot.py`, puis redéploie et remplace le panneau avec `/installer`. Le logo et la bannière sont facultatifs ; aucune image Betclic n’est réutilisée.

## Fonctionnement pour les membres

- **Ajouter / modifier mon compte** ouvre un formulaire Discord privé. L’adresse est validée syntaxiquement puis remplace la précédente pour ce membre.
- **Voir mon e-mail** affiche uniquement au membre son adresse et le statut « non vérifié ».
- **Supprimer mon association** efface immédiatement sa ligne dans la base active.
- **`/compte membre:@membre`** permet uniquement aux administrateurs de consulter, dans une réponse privée, l’adresse déclarée par un membre. Les contrôles d’autorisation sont aussi exécutés côté bot.

Plusieurs membres peuvent déclarer la même adresse : aucune preuve de propriété n’est collectée. Ne traite donc pas ces déclarations comme des identités vérifiées ou une preuve d’éligibilité.

## Données et exploitation

La base enregistre uniquement l’identifiant du serveur, l’identifiant Discord du membre, son adresse et la date de dernière modification UTC. Les e-mails ne sont pas envoyés à BiggerZ, ne sont pas publiés dans un salon et ne sont pas inscrits volontairement dans les logs du bot. Ils sont accessibles aux administrateurs via `/compte`, aux personnes qui ont accès au volume Railway et aux systèmes de Discord qui traitent le formulaire.

SQLite n’est pas chiffré par l’application. Restreins l’accès au projet Railway. Les données restent conservées jusqu’à suppression par le membre ou intervention de l’exploitant ; quitter le serveur ne les supprime pas automatiquement. La suppression vise la base active, pas d’éventuelles sauvegardes externes. Définis avec le client la durée de conservation et la politique des sauvegardes avant la mise en service, et adapte le paragraphe « Tes données » dans `panels()` si besoin.

Le bot est conçu pour un seul serveur. Pour plusieurs clients, déploie un service, un volume et une application Discord distincts par client.

## Vérification après déploiement

1. Utilise `/installer` avec un administrateur ; avec un compte non administrateur, les commandes d’administration doivent être refusées ou invisibles.
2. Saisis une adresse de test : vérifie que la confirmation et la consultation sont privées.
3. Modifie-la ; redémarre Railway ; vérifie que les boutons fonctionnent encore et que l’adresse modifiée est conservée.
4. Supprime l’association et vérifie avec « Voir mon e-mail » et `/compte` qu’elle a disparu.

Tests automatisés locaux (Python 3.9+ ; production Docker : Python 3.12) :

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Ces tests ne se connectent pas à Discord. Une validation réelle nécessite ton token, ton serveur et ton déploiement Railway.

## Dépannage

- **Token invalide** : récupère un nouveau token dans Discord, mets à jour `DISCORD_TOKEN`, redéploie.
- **Commande absente** : vérifie `DISCORD_GUILD_ID`, l’invitation avec `applications.commands` et les logs. Recharge Discord.
- **Panneau impossible à publier** : vérifie les permissions du bot dans le salon, y compris ses restrictions locales.
- **Données perdues après déploiement** : vérifie le montage du volume sur `/data` et `DATABASE_PATH`.
- **Bouton sans réponse** : vérifie que Railway est actif et que le bot apparaît connecté ; un formulaire déjà ouvert avant un redémarrage doit être rouvert.

## Sources techniques

- Discord : https://docs.discord.com/developers/interactions/receiving-and-responding
- discord.py (interactions) : https://discordpy.readthedocs.io/en/stable/interactions/api.html
- Vues persistantes : https://github.com/Rapptz/discord.py/blob/master/examples/views/persistent.py
- Railway (volumes) : https://docs.railway.com/volumes
- Site BiggerZ consulté pour le contexte : https://www.biggerz.com/
