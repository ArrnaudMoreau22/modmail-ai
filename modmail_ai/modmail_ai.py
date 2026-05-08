"""
Plugin ModMail IA - Brawl Stars
https://github.com/[votre-org]/modmail-ai-poc

Plugin public. AUCUN credential hardcodé.
Configuration via commandes admin stockées dans le plugin DB de ModMail (MongoDB).

COMMANDES :
  ?aiseturl <url>    — URL du backend IA (ADMINISTRATOR)
  ?aisettoken <token>— Token d'auth backend (ADMINISTRATOR, message supprimé)
  ?aistatus          — État de configuration (MODERATOR)
  ?aireset           — Supprime la configuration (ADMINISTRATOR)
  ?aireview          — Analyse le ticket courant (MODERATOR)

GARANTIES ABSOLUES :
  - Ne répond jamais directement au joueur.
  - Ne ferme jamais le ticket.
  - Ne déclenche jamais de sanction.
  - Ne lance jamais de commande UnbelievaBoat.
  - Aucun credential dans le code source.
"""
import discord
from discord.ext import commands
from core import checks
from core.models import PermissionLevel

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

# Clés de configuration stockées dans le plugin DB
_KEY_URL = "backend_url"
_KEY_TOKEN = "backend_token"

# Activation de l'analyse automatique — désactivée par défaut, toujours
_ENABLE_AUTO_REVIEW = False

COLOR_INFO = discord.Color.blue()
COLOR_WARNING = discord.Color.orange()
COLOR_DANGER = discord.Color.red()
COLOR_SUCCESS = discord.Color.green()
COLOR_NEUTRAL = discord.Color.greyple()


# ── Helpers embeds ────────────────────────────────────────────────────────────

def _trunc(text: str, limit: int = 1024) -> str:
    if not text:
        return "_(vide)_"
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _risk_color(risk_level: str) -> discord.Color:
    return {
        "low": COLOR_SUCCESS,
        "medium": COLOR_WARNING,
        "high": COLOR_DANGER,
        "critical": discord.Color.dark_red(),
    }.get(risk_level, COLOR_NEUTRAL)


def _build_main_embed(review: dict, metadata: dict, thread_id: str) -> discord.Embed:
    risk_level = review.get("risk_level", "low")
    escalation = review.get("escalation_required", False)
    is_safe = metadata.get("is_safe", True)
    dry_run = metadata.get("dry_run", True)

    title = "🤖 Analyse IA — ModMail"
    if escalation:
        title = "🚨 Analyse IA — ESCALADE REQUISE"
    elif not is_safe:
        title = "⚠️ Analyse IA — Vérification requise"

    embed = discord.Embed(title=title, color=_risk_color(risk_level))

    embed.add_field(
        name="📋 Résumé (staff)",
        value=_trunc(review.get("ticket_summary_staff") or "_(non disponible)_"),
        inline=False,
    )
    embed.add_field(
        name="❓ Demande du joueur",
        value=_trunc(review.get("user_issue") or "_(non déterminé)_"),
        inline=False,
    )

    reported = review.get("reported_users") or []
    if reported:
        embed.add_field(
            name="👤 Utilisateurs signalés",
            value=", ".join(str(u) for u in reported),
            inline=True,
        )

    embed.add_field(
        name="🔍 Preuves",
        value=_trunc(review.get("evidence_summary") or "_(aucune preuve analysée)_"),
        inline=False,
    )

    risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴", "critical": "⛔"}.get(
        risk_level, "⚪"
    )
    embed.add_field(name="⚠️ Risque", value=f"{risk_emoji} **{risk_level.upper()}**", inline=True)
    embed.add_field(
        name="🔄 Escalade",
        value="🚨 **OUI**" if escalation else "✅ Non",
        inline=True,
    )
    embed.add_field(name="🤖 Modèle", value=metadata.get("model_used", "inconnu"), inline=True)

    if escalation:
        reasons = review.get("escalation_reasons") or []
        if reasons:
            embed.add_field(
                name="🚨 Raisons d'escalade",
                value=_trunc("\n".join(f"• {r}" for r in reasons)),
                inline=False,
            )

    missing = review.get("missing_information") or []
    if missing:
        embed.add_field(
            name="❔ Informations manquantes",
            value=_trunc("\n".join(f"• {m}" for m in missing)),
            inline=False,
        )

    safety_flags = metadata.get("safety_flags") or []
    if safety_flags:
        embed.add_field(
            name="🛡️ Flags de sécurité",
            value=_trunc("\n".join(f"• {f}" for f in safety_flags[:5])),
            inline=False,
        )

    footer_parts = [f"Ticket {thread_id}"]
    if dry_run:
        footer_parts.append("MODE DRY-RUN")
    if not is_safe:
        footer_parts.append("⚠️ UNSAFE — Validation requise")
    embed.set_footer(text=" | ".join(footer_parts))
    return embed


def _build_reply_embed(review: dict, is_safe: bool) -> discord.Embed:
    embed = discord.Embed(
        title="💬 Réponse proposée au joueur",
        color=COLOR_SUCCESS if is_safe else COLOR_WARNING,
    )
    embed.add_field(
        name="📝 Texte proposé (à valider avant envoi)",
        value=_trunc(review.get("suggested_user_reply") or "_(aucune réponse suggérée)_"),
        inline=False,
    )
    if not is_safe:
        embed.add_field(
            name="⚠️ Attention",
            value="La réponse a été supprimée ou modifiée pour raison de sécurité. "
            "Rédiger manuellement la réponse au joueur.",
            inline=False,
        )
    embed.set_footer(
        text="⚠️ Relire et adapter avant tout envoi. Ne pas copier-coller sans vérification."
    )
    return embed


def _build_action_embed(review: dict) -> discord.Embed:
    embed = discord.Embed(title="⚙️ Action staff recommandée", color=COLOR_NEUTRAL)
    embed.add_field(
        name="📌 Action recommandée",
        value=_trunc(review.get("suggested_staff_action") or "_(non déterminée)_"),
        inline=False,
    )

    sanction = review.get("suggested_sanction") or {}
    if sanction.get("should_sanction"):
        conf = sanction.get("confidence", "low")
        conf_emoji = {"low": "🔴", "medium": "🟡", "high": "🟢"}.get(conf, "⚪")
        embed.add_field(
            name="⚖️ Sanction suggérée",
            value=(
                f"**Type** : {sanction.get('sanction_type') or 'inconnue'}\n"
                f"**Niveau** : {sanction.get('sanction_level') or '?'}\n"
                f"**Raison** : {_trunc(sanction.get('reason') or '', 300)}\n"
                f"**Confiance** : {conf_emoji} {conf.upper()}"
            ),
            inline=False,
        )
        embed.add_field(
            name="⚠️ IMPORTANT",
            value="Suggestion uniquement. **Non appliquée automatiquement.** "
            "Un modérateur doit valider et exécuter manuellement si jugé approprié.",
            inline=False,
        )
    else:
        embed.add_field(
            name="⚖️ Sanction", value="✅ Aucune sanction suggérée.", inline=False
        )

    history = review.get("punishment_history_summary_staff")
    if history:
        embed.add_field(
            name="📁 Historique (staff uniquement)", value=_trunc(history), inline=False
        )

    embed.set_footer(text="⚠️ Validation humaine requise avant toute sanction.")
    return embed


# ── Cog principal ─────────────────────────────────────────────────────────────

class ModMailAI(commands.Cog):
    """
    Cog ModMail IA — Analyse de tickets via backend IA privé.

    Configuration stockée dans la base plugin ModMail (aucun credential dans le code).
    """

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.plugin_db.get_partition(self)
        if not HAS_AIOHTTP:
            print("[ModMailAI] AVERTISSEMENT : aiohttp non disponible (normalement inclus avec discord.py).")

    # ── Accès config DB ───────────────────────────────────────────────────────

    async def _get_config(self, key: str):
        doc = await self.db.find_one({"_id": key})
        return doc["value"] if doc else None

    async def _set_config(self, key: str, value: str) -> None:
        await self.db.find_one_and_update(
            {"_id": key}, {"$set": {"value": value}}, upsert=True
        )

    async def _delete_config(self, key: str) -> None:
        await self.db.delete_one({"_id": key})

    # ── Commandes de configuration ────────────────────────────────────────────

    @commands.command(name="aiseturl")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def ai_set_url(self, ctx, url: str):
        """Configure l'URL du backend IA. Réservé aux administrateurs."""
        if not url.startswith(("http://", "https://")):
            await ctx.send(
                embed=discord.Embed(
                    title="❌ URL invalide",
                    description="L'URL doit commencer par `http://` ou `https://`.",
                    color=COLOR_DANGER,
                )
            )
            return
        clean_url = url.rstrip("/")
        await self._set_config(_KEY_URL, clean_url)
        await ctx.send(
            embed=discord.Embed(
                title="✅ URL backend configurée",
                description=f"Backend URL enregistrée : `{clean_url}`",
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(name="aisettoken")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def ai_set_token(self, ctx, token: str):
        """
        Configure le token d'authentification backend.
        Le message Discord est supprimé immédiatement pour protéger le token.
        """
        # Supprimer immédiatement le message pour ne jamais exposer le token
        try:
            await ctx.message.delete()
        except (discord.Forbidden, discord.HTTPException):
            pass  # Pas de permission de suppression — on continue quand même

        if not token.strip():
            await ctx.send(
                embed=discord.Embed(
                    title="❌ Token invalide",
                    description="Le token ne peut pas être vide.",
                    color=COLOR_DANGER,
                )
            )
            return

        await self._set_config(_KEY_TOKEN, token.strip())

        # Réponse générique — ne jamais répéter le token
        await ctx.send(
            embed=discord.Embed(
                title="✅ Token configuré",
                description="Le token d'authentification a été enregistré.",
                color=COLOR_SUCCESS,
            )
        )

    @commands.command(name="aistatus")
    @checks.has_permissions(PermissionLevel.MODERATOR)
    async def ai_status(self, ctx):
        """Affiche l'état de configuration du plugin IA. Ne révèle jamais le token."""
        backend_url = await self._get_config(_KEY_URL)
        has_token = bool(await self._get_config(_KEY_TOKEN))

        embed = discord.Embed(title="⚙️ Configuration ModMail AI", color=COLOR_INFO)
        embed.add_field(
            name="Backend URL",
            value=f"`{backend_url}`" if backend_url else "❌ Non configurée",
            inline=False,
        )
        embed.add_field(
            name="Token",
            value="✅ Configuré" if has_token else "❌ Non configuré",
            inline=True,
        )
        embed.add_field(
            name="aiohttp",
            value="✅ Disponible" if HAS_AIOHTTP else "❌ Non disponible (erreur d'environnement)",
            inline=True,
        )
        if not backend_url or not has_token:
            embed.add_field(
                name="⚠️ Setup requis",
                value=(
                    "Un administrateur doit configurer le plugin :\n"
                    "• `?aiseturl <url_backend>`\n"
                    "• `?aisettoken <token>` _(message supprimé automatiquement)_"
                ),
                inline=False,
            )
        embed.set_footer(text="Le token n'est jamais affiché.")
        await ctx.send(embed=embed)

    @commands.command(name="aireset")
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def ai_reset(self, ctx):
        """Supprime toute la configuration IA stockée dans la base plugin."""
        await self._delete_config(_KEY_URL)
        await self._delete_config(_KEY_TOKEN)
        await ctx.send(
            embed=discord.Embed(
                title="🗑️ Configuration supprimée",
                description="L'URL et le token ont été effacés de la base plugin.",
                color=COLOR_WARNING,
            )
        )

    # ── Commande principale ───────────────────────────────────────────────────

    @commands.command(name="aireview")
    @checks.has_permissions(PermissionLevel.MODERATOR)
    async def ai_review(self, ctx):
        """
        Lance une analyse IA du ticket courant et poste les résultats côté staff.

        GARANTIES :
        - Aucun message au joueur.
        - Aucun ticket fermé.
        - Aucune sanction exécutée.
        - Aucune commande UnbelievaBoat.
        """
        if not HAS_AIOHTTP:
            await ctx.send(
                embed=discord.Embed(
                    title="❌ aiohttp indisponible",
                    description=(
                        "`aiohttp` n'est pas accessible dans cet environnement.\n"
                        "Ce module est normalement inclus avec discord.py — "
                        "contacter l'administrateur du bot."
                    ),
                    color=COLOR_DANGER,
                )
            )
            return

        backend_url = await self._get_config(_KEY_URL)
        backend_token = await self._get_config(_KEY_TOKEN)

        if not backend_url or not backend_token:
            await ctx.send(
                embed=discord.Embed(
                    title="❌ Plugin non configuré",
                    description=(
                        "Le plugin IA n'a pas encore été configuré.\n"
                        "Un **administrateur** doit exécuter :\n"
                        "• `?aiseturl <url_backend>`\n"
                        "• `?aisettoken <token>`"
                    ),
                    color=COLOR_DANGER,
                )
            )
            return

        thread = await self.bot.threads.find(channel=ctx.channel)
        if not thread:
            await ctx.send(
                embed=discord.Embed(
                    title="❌ Hors contexte",
                    description="Cette commande doit être utilisée dans un canal de ticket ModMail.",
                    color=COLOR_DANGER,
                )
            )
            return

        loading_msg = await ctx.send(
            embed=discord.Embed(
                title="🔄 Analyse en cours…",
                description="Le backend IA analyse le ticket. Cela peut prendre quelques secondes.",
                color=COLOR_INFO,
            )
        )

        guild_id = str(ctx.guild.id) if ctx.guild else ""
        thread_id = str(thread.id)

        try:
            payload = await self._build_payload(thread, ctx)
        except Exception as e:
            await loading_msg.edit(
                embed=discord.Embed(
                    title="❌ Erreur de préparation",
                    description=f"Impossible de préparer le contexte du ticket : {e}",
                    color=COLOR_DANGER,
                )
            )
            return

        try:
            response_data = await self._call_backend(
                backend_url=backend_url,
                backend_token=backend_token,
                payload=payload,
                guild_id=guild_id,
                thread_id=thread_id,
            )
        except aiohttp.ClientResponseError as e:
            if e.status in (401, 403):
                desc = (
                    "Le backend a refusé la requête (token invalide ou expiré).\n"
                    "Un administrateur doit reconfigurer le token avec `?aisettoken`."
                )
            else:
                desc = f"Le backend a retourné une erreur HTTP {e.status}."
            await loading_msg.edit(
                embed=discord.Embed(title="❌ Erreur backend", description=desc, color=COLOR_DANGER)
            )
            return
        except Exception as e:
            await loading_msg.edit(
                embed=discord.Embed(
                    title="❌ Backend inaccessible",
                    description=f"Impossible de joindre le backend IA : {e}",
                    color=COLOR_DANGER,
                )
            )
            return

        try:
            await loading_msg.delete()
        except Exception:
            pass

        review = response_data.get("review") or {}
        metadata = response_data.get("metadata") or {}
        resp_thread_id = response_data.get("thread_id") or thread_id
        is_safe = metadata.get("is_safe", True)

        await ctx.send(embed=_build_main_embed(review, metadata, resp_thread_id))
        await ctx.send(embed=_build_reply_embed(review, is_safe))
        await ctx.send(embed=_build_action_embed(review))

    # ── Helpers privés ────────────────────────────────────────────────────────

    async def _build_payload(self, thread, ctx) -> dict:
        """Collecte et normalise le contexte du thread ModMail."""
        recipient = thread.recipient

        messages = []
        async for message in ctx.channel.history(limit=50, oldest_first=True):
            is_mod = False
            is_official_reply = False
            is_internal = False

            if message.author == self.bot.user:
                mod_color = self.bot.config.get("mod_color")
                for embed in message.embeds:
                    if mod_color and embed.color and embed.color.value == mod_color:
                        is_mod = True
                        is_official_reply = True

            messages.append(
                {
                    "id": str(message.id),
                    "content": message.content or "",
                    "author_id": str(message.author.id),
                    "author_display_name": message.author.display_name,
                    "timestamp": message.created_at.isoformat(),
                    "is_mod": is_mod,
                    "is_official_reply": is_official_reply,
                    "internal": is_internal,
                    "author_role": "staff" if is_mod else "user",
                    "attachments": [
                        {
                            "id": str(att.id),
                            "url": att.url,
                            "filename": att.filename,
                            "content_type": getattr(att, "content_type", None),
                        }
                        for att in message.attachments
                    ],
                    "embeds": [
                        {
                            "title": emb.title,
                            "description": emb.description,
                            "color": emb.color.value if emb.color else None,
                            "fields": [
                                {"name": f.name, "value": f.value} for f in emb.fields
                            ],
                        }
                        for emb in message.embeds
                    ],
                }
            )

        return {
            "thread_id": str(thread.id),
            "channel_id": str(ctx.channel.id),
            "guild_id": str(ctx.guild.id) if ctx.guild else "",
            "recipient_user_id": str(recipient.id) if recipient else None,
            "recipient_display_name": str(recipient) if recipient else None,
            "messages": messages,
            "attachments": [],
            "options": {"requested_by": str(ctx.author.id)},
        }

    async def _call_backend(
        self,
        backend_url: str,
        backend_token: str,
        payload: dict,
        guild_id: str,
        thread_id: str,
    ) -> dict:
        """
        Appelle le backend IA via aiohttp (inclus avec discord.py, aucun pip install requis).
        Le token n'est jamais loggé. Envoyé uniquement dans le header Authorization.
        """
        headers = {
            "Authorization": f"Bearer {backend_token}",
            "X-Discord-Guild-ID": guild_id,
            "X-ModMail-Thread-ID": thread_id,
        }
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{backend_url}/api/review-ticket",
                json=payload,
                headers=headers,
                timeout=timeout,
            ) as response:
                response.raise_for_status()
                return await response.json()

    # ── Listener automatique (désactivé par défaut) ───────────────────────────

    @commands.Cog.listener()
    async def on_thread_reply(self, thread, from_mod, message, anonymous, plain):
        """
        Analyse automatique à chaque réponse.
        TOUJOURS désactivée dans ce POC.
        Ne jamais activer sans avoir validé le comportement complet du backend.
        """
        if not _ENABLE_AUTO_REVIEW:
            return
        # TODO: implémenter rate-limiting et appel backend
        # IMPORTANT : charger backend_url et backend_token depuis self.db, jamais depuis l'env.


async def setup(bot):
    """Chargement du Cog ModMail."""
    await bot.add_cog(ModMailAI(bot))
