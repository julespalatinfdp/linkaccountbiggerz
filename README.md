# BiggerZ — liaison Discord via l’API partenaire

Version staging utilisant la documentation BiggerZ Discord v1 fournie le 20 octobre 2026. Aucun e-mail, mot de passe ou code de connexion n’est demandé au membre. Le membre confirme sur BiggerZ après connexion à son compte.

## Mettre à jour GitHub

Dépose le contenu de ce dossier à la racine du dépôt du bot de liaison (pas celui des annonces de gains).

Remplace entièrement :
- `bot.py`
- `storage.py`
- `requirements.txt`
- `Dockerfile`
- `railway.toml`

Ajoute `biggerz.py`. Le Dockerfile doit copier les trois fichiers Python. Remplace également les anciens tests par le dossier `tests` fourni. Les fichiers cachés sont visibles sur Mac avec Cmd + Maj + point.

Les fichiers `.env.example`, `.gitignore`, `.dockerignore` et ce guide ne contiennent aucun secret réel.

## Variables Railway

Conserve le token du bot et l’identifiant de ton serveur. Ajoute ou modifie :

```env
DISCORD_TOKEN=TON_TOKEN_DISCORD_EXISTANT
DISCORD_GUILD_ID=ID_DE_TON_SERVEUR
BIGGERZ_API_BASE_URL=https://v2biggerz.live/nitro/integrations/discord/v1
BIGGERZ_API_KEY=LA_CLE_STAGING_FOURNIE_PAR_LE_DEV
DATABASE_PATH=/data/biggerz-staging.sqlite3
```

La clé API doit être saisie exactement telle que fournie par le développeur. Elle n’est pas incluse dans le projet. Le fichier `.env.example` est un modèle ; le bot lit les variables injectées par Railway, pas un fichier `.env`.

Conserve le volume Railway monté sur `/data` et une seule réplique. Le bot doit tourner en continu : pas de mise en veille. Aucun domaine public, port HTTP ou webhook n’est nécessaire.

La bannière Discord précédemment fournie reste la valeur par défaut. Si elle n’apparaît plus, définis `BANNER_URL` avec une URL HTTPS publique d’image à jour, idéalement stable. Une valeur vide masque l’image. Les anciennes variables de description et de salons ne sont pas utilisées : le texte du panneau est dans `panels()`.

## Publier le nouveau panneau

1. Attends la réussite du déploiement et la connexion du bot.
2. Supprime l’ancien panneau Discord qui parle d’e-mail.
3. Lance `/installer` dans le salon souhaité avec un administrateur.
4. Épingle le nouveau message.

Les boutons de l’ancien panneau restent reconnus par la nouvelle version, mais leurs anciens libellés ne se mettent pas à jour automatiquement. `/installer` publie un nouveau message à chaque appel.

Le bot nécessite seulement View Channels, Send Messages et Embed Links dans le salon. L’invitation utilise les scopes `bot` et `applications.commands`. Aucun intent privilégié ni permission Administrateur du bot n’est nécessaire.

## Parcours membre

- **Link / update my account** ou `/link` : génération d’un lien privé à usage unique, valable 15 minutes.
- Le membre ouvre le bouton privé, se connecte sur le staging et clique sur Confirm.
- Le bot vérifie la demande environ toutes les quatre secondes à faible charge. Il ralentit naturellement quand plusieurs demandes partagent la limite API.
- La réponse privée initiale est remplacée par une confirmation si le bot est resté actif et que le message Discord peut encore être modifié.
- **View my account** ou `/account` : lecture du lien actuel directement depuis l’API BiggerZ.
- **Unlink my account** ou `/unlink` : confirmation privée, puis suppression via l’API.
- `/compte membre:@membre` : consultation privée réservée aux administrateurs.

Un clic répété pendant une demande en attente ne crée pas un nouveau lien. Si le membre perd son message privé après un redémarrage, il peut vérifier son compte avec `/account` ou attendre l’expiration pour générer un nouveau lien. Les URL privées ne sont pas stockées en base.

Si une demande est encore en attente, il faut l’annuler sur BiggerZ ou attendre son expiration avant de supprimer une association existante. La documentation ne fournit pas d’endpoint pour annuler une demande en attente depuis le bot.

## Synchronisation et stockage

Les changements faits côté BiggerZ sont récupérés toutes les 60 secondes. Les pages pleines sont parcourues immédiatement, avec respect du limiteur global. Le bot applique les événements et sauvegarde le curseur dans la même transaction SQLite. Toute suppression utilise les deux identifiants, quel que soit le motif. Les événements inconnus ne bloquent pas la synchronisation.

Le cache local est alimenté uniquement par les événements dans l’ordre du serveur. Les consultations membres passent par l’API pour obtenir le lien actuel. La clé API et les URL privées ne sont pas stockées dans SQLite ni volontairement journalisées.

La base conserve : les paires d’identifiants vérifiées, le curseur d’événements, les identifiants de demandes en attente et leur expiration, ainsi que l’environnement API. Les identifiants échangés avec BiggerZ restent des chaînes de caractères.

La nouvelle base staging est distincte de l’ancienne base d’e-mails. Les anciennes associations déclaratives ne deviennent jamais vérifiées automatiquement. Ce déploiement n’efface pas l’ancienne base ni ses sauvegardes : l’exploitant doit gérer leur conservation ou suppression séparément.

Le code respecte un rythme global inférieur à 100 appels/minute (limite documentée : 120), attend Retry-After après un 429 et utilise un délai croissant lors des nouvelles tentatives après les erreurs réseau ou 5xx. Les requêtes ont un délai maximal de 20 secondes et quatre tentatives au plus par opération. Les tâches de fond réessaient au cycle suivant. Pour un grand nombre de confirmations simultanées, envisager les webhooks avec BiggerZ.

Les accès VIP, cadeaux et quêtes mentionnés dans le panneau ne sont pas attribués par ce code : l’intégration actuelle porte uniquement sur la liaison des comptes.

## Test réel sur staging

1. Clique sur Link / update my account depuis TON compte Discord.
2. Vérifie que seul ton compte Discord voit le bouton privé.
3. Ouvre le lien et connecte-toi avec le compte BiggerZ autorisé, puis confirme.
4. Utilise `/account` : il doit afficher l’identifiant BiggerZ.
5. Redémarre le service Railway et vérifie de nouveau `/account`.
6. Utilise `/unlink`, confirme, puis vérifie l’absence de liaison avec `/account`.
7. Relie de nouveau le compte, puis délie-le depuis BiggerZ. Vérifie `/account` et laisse un cycle de 60 secondes pour synchroniser le cache.
8. Teste également l’annulation et l’expiration d’une demande.

Ne partage pas le lien privé : toute personne qui l’ouvre en étant connectée peut associer SON compte BiggerZ à l’identifiant Discord concerné.

## Production

Après validation par le développeur, utiliser la clé de production et :

```env
BIGGERZ_API_BASE_URL=https://www.biggerz.com/nitro/integrations/discord/v1
DATABASE_PATH=/data/biggerz-production.sqlite3
```

Ne réutilise pas la base staging en production : les curseurs et les comptes appartiennent à des environnements distincts. Le bot refuse un changement d’environnement sur une base déjà initialisée.

## Tests automatisés

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

17 tests exécutés avec succès localement. Ils couvrent notamment les réponses privées, les demandes expirées, la reprise du stockage, la pagination, la suppression ciblée, les réponses 429 et les droits administrateur déclarés. Les appels API et Discord sont simulés : aucun test connecté à votre compte BiggerZ ou au serveur Discord n’a été effectué.
