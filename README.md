# Plugin ModMail AI

Plugin public pour `modmail-dev/modmail`. **Aucun credential dans le code.**

## Installation

1. Charger via URL GitHub : `?plugin load https://github.com/[org]/modmail-ai-poc/blob/main/plugin/modmail_ai.py`
2. Installer `httpx` sur l'environnement du bot : `pip install httpx`
3. Configurer via les commandes admin (voir ci-dessous).

## Configuration (commandes admin)

Toute la configuration est stockée dans la base plugin ModMail (MongoDB du bot).
Aucune variable d'environnement à toucher sur le bot.

```
?aiseturl https://votre-backend.example.com   ← URL du backend (ADMINISTRATOR)
?aisettoken votre_token_secret                ← Token auth, message supprimé (ADMINISTRATOR)
?aistatus                                     ← Vérifie la config (MODERATOR)
?aireset                                      ← Supprime la config (ADMINISTRATOR)
```

> `?aisettoken` supprime **immédiatement** le message Discord pour ne pas exposer le token.

## Commandes

| Commande | Permission | Description |
|---|---|---|
| `?aiseturl <url>` | ADMINISTRATOR | Configure l'URL du backend IA |
| `?aisettoken <token>` | ADMINISTRATOR | Configure le token (message supprimé) |
| `?aistatus` | MODERATOR | Affiche l'état de configuration |
| `?aireset` | ADMINISTRATOR | Supprime la configuration |
| `?aireview` | MODERATOR | Lance une analyse du ticket courant |

## Sécurité

- Aucun credential dans le code source (plugin public GitHub).
- Le token est stocké dans la base plugin ModMail du bot (contrôlée par le serveur).
- Le token n'est **jamais** affiché, loggé ou répété dans une réponse.
- Le message `?aisettoken` est supprimé immédiatement après traitement.
- Les requêtes HTTP incluent les headers `X-Discord-Guild-ID` et `X-ModMail-Thread-ID`.

## Garanties

- Ne répond **jamais** directement au joueur.
- Ne ferme **jamais** le ticket.
- Ne déclenche **jamais** de sanction.
- Ne lance **jamais** de commande UnbelievaBoat.

## Analyse automatique

L'analyse automatique via `on_thread_reply` est **désactivée dans le code** (`_ENABLE_AUTO_REVIEW = False`).
Ne pas modifier sans avoir validé le comportement complet du backend.
