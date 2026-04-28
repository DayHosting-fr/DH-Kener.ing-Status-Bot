import json
import aiohttp
import asyncio
import time
import disnake
from disnake.ext import commands, tasks
from datetime import datetime, timezone
import traceback
from utils.database import Database


# Charger la configuration depuis le fichier 'config.json'
with open("config.json", encoding="utf-8") as f:
    configs = json.load(f)

EXCLUDED_CATEGORIES = configs.get("EXCLUDED_CATEGORIES", [])
API_URL = configs["KENER_API_URL"]
API_KEY = configs["KENER_API_KEY"]
CHANNEL_ID = configs["CHANNEL_ID"]
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

class KenerEmbed(commands.Cog):
    def __init__(self, bot: commands.Bot):
        # Initialisation du bot et des variables de stockage pour le canal et le message
        self.bot = bot
        self.channel = None
        self.message = None
        self.session = None

    def cog_unload(self):
        # Fermer la session aiohttp lors du déchargement du cog
        if self.session and not self.session.closed:
            asyncio.create_task(self.session.close())


    async def cog_load(self):
        """Called when the cog is loaded."""
        if not self.session:
            timeout = aiohttp.ClientTimeout(total=10)
            self.session = aiohttp.ClientSession(headers=HEADERS, timeout=timeout)
        
        self.channel = self.bot.get_channel(int(CHANNEL_ID))
        if self.channel:
            try:
                import os
                if os.path.exists("message_id.txt"):
                    with open("message_id.txt", "r") as f:
                        msg_id = int(f.read().strip())
                        self.message = await self.channel.fetch_message(msg_id)
            except Exception as e:
                print(f"Could not fetch existing message: {e}")
            
            if not self.message:
                try:
                    embed = await self.create_embed()
                    self.message = await self.channel.send(embed=embed)
                    with open("message_id.txt", "w") as f:
                        f.write(str(self.message.id))
                except Exception as e:
                    print(f"Failed to create initial message: {e}")

        if not self.auto_update.is_running():
            self.auto_update.start()

    @commands.Cog.listener()
    async def on_ready(self):
        # Ensure initialization even if loaded before on_ready
        await self.cog_load()

    async def fetch_data(self, endpoint, params=None):
        # Fonction générique pour récupérer des données de l'API Kener v4 via aiohttp
        if not self.session:
            timeout = aiohttp.ClientTimeout(total=10)
            self.session = aiohttp.ClientSession(headers=HEADERS, timeout=timeout)
            
        try:
            url = f"{API_URL}/api/v4/{endpoint}"
            async with self.session.get(url, params=params) as response:
                if response.status == 404:
                    return {}
                response.raise_for_status()
                return await response.json()
        except Exception as e:
            print(f"Error fetching {endpoint}: {e}")
            return {}

    async def fetch_latest_data_point(self, monitor_tag):
        # Récupère le dernier point de données pour obtenir le vrai statut (UP/DOWN)
        now = int(time.time() // 60 * 60)
        # On essaie la minute actuelle puis la minute précédente
        for ts in [now, now - 60]:
            data = await self.fetch_data(f"monitors/{monitor_tag}/data/{ts}")
            if data and data.get("data"):
                return data.get("data")
        return None


    async def create_embed(self):
        # Fonction pour créer un embed avec les données de statut des serveurs
        embed = disnake.Embed(
            title=":satellite: État des serveurs",
            color=disnake.Color.blue(),
            timestamp=datetime.utcnow()
        )
        embed.set_author(name="DayHosting", icon_url=configs.get("AUTHOR_ICON"))
        embed.set_thumbnail(url=configs.get("THUMBNAIL_URL"))

        embed.description = ("Les statuts sur cette page sont actualisés toutes les 5 minutes. "
                             "\nUne version web est disponible [ici](https://status.dayhosting.fr)")

        # Récupérer les données via les pages (v4)
        data_pages = await self.fetch_data("pages")
        pages = data_pages.get("pages", [])
        
        # LOGS POUR DÉBOGAGE
        print(f"DEBUG: Nombre de pages récupérées : {len(pages)}")

        # Si aucune page n'est récupérée, afficher un message d'erreur
        if not pages:
            embed = disnake.Embed(
                title="Status des serveurs",
                description=("Une erreur est survenue lors de la récupération des pages de status, "
                             "merci de patienter quelques instants."),
                color=disnake.Color.red(),
                timestamp=datetime.utcnow()
            )
            return embed

        # Récupérer tous les moniteurs pour faire le lien avec les tags
        data_monitors = await self.fetch_data("monitors")
        monitors_list = data_monitors.get("monitors", [])
        monitor_map = {m["tag"]: m for m in monitors_list if "tag" in m}
        print(f"DEBUG: Nombre de moniteurs globaux récupérés : {len(monitors_list)}")

        # Récupérer les incidents pour les messages d'état
        data_incidents = await self.fetch_data("incidents")
        incidents = data_incidents.get("incidents", [])

        # Organiser les incidents par moniteur (tag)
        monitor_incidents = {}
        for incident in incidents:
            impacted = incident.get("monitors", [])
            for mon_impact in impacted:
                tag = mon_impact.get("monitor_tag")
                if tag:
                    monitor_incidents.setdefault(tag, []).append(incident)

        # Pré-charger les status réels pour tous les moniteurs en parallèle
        monitor_tags = []
        for page in pages:
            if page.get("page_title") in EXCLUDED_CATEGORIES:
                continue
            for mon in page.get("monitors", []):
                tag = (mon.get("monitor_tag") or mon.get("tag")) if isinstance(mon, dict) else str(mon)
                if tag and tag not in monitor_tags:
                    monitor_tags.append(tag)
        
        print(f"DEBUG: Récupération des data points pour {len(monitor_tags)} moniteurs...")
        data_points_results = await asyncio.gather(*[self.fetch_latest_data_point(tag) for tag in monitor_tags])
        real_time_status = {tag: dp.get("status") for tag, dp in zip(monitor_tags, data_points_results) if dp}

        # Ajouter chaque page et ses moniteurs à l'embed
        for page in pages:
            page_title = page.get("page_title", "Sans titre")
            mons = page.get("monitors", [])
            
            if page_title in EXCLUDED_CATEGORIES:
                continue

            print(f"DEBUG: Page: {page_title} | Nombre de moniteurs : {len(mons)}")
            if not mons:
                continue
                
            field_value = ""
            for mon in mons:
                try:
                    if isinstance(mon, dict):
                        tag = mon.get("monitor_tag") or mon.get("tag")
                    else:
                        tag = str(mon)
                    
                    if not tag:
                        continue

                    mon_data = monitor_map.get(tag) or (mon if isinstance(mon, dict) else {})
                    
                    name = mon_data.get("name") or tag
                    
                    # Utiliser le statut réel du data point si disponible, sinon le statut global
                    status = real_time_status.get(tag) or mon_data.get("status") or "UP"
                    status = str(status).upper()
                    
                    print(f"DEBUG:   - Moniteur: {name} (Tag: {tag}) | Status: {status}")
                    
                    icon = configs["STATUS_ICONS"].get(status, configs["STATUS_ICONS"].get("UNKNOWN", "❓"))


                    # Ajouter des messages pour chaque incident lié au moniteur
                    incident_msgs = ""
                    for inc in monitor_incidents.get(tag, []):
                        try:
                            if inc.get("state") == "RESOLVED" and inc.get("incident_type") != "MAINTENANCE":
                                continue
                            inc_type = inc.get("incident_type")
                            reason = inc.get("title", "Raison inconnue")
                            STATE = str(inc.get("state") or "Incident").upper()
                            
                            STATE_text = "Incident"
                            if STATE == "INVESTIGATING":
                                STATE_text = "⚠️ En cours d'investigation"
                            elif STATE == "IDENTIFIED":
                                STATE_text = "🔍 Identifié"
                            elif STATE == "MONITORING":
                                STATE_text = "👀 En cours de surveillance"
                            elif inc_type == "MAINTENANCE":
                                STATE_text = "🔧 En maintenance"

                            if STATE != "RESOLVED" or inc_type == "MAINTENANCE":
                                incident_msgs += f"\n   {STATE_text} - Raison : `{reason}`\n"
                                if inc_type == "MAINTENANCE":
                                    icon = configs["STATUS_ICONS"].get("MAINTENANCE", icon)
                        except Exception as e_inc:
                            print(f"DEBUG:     - Erreur incident pour {tag}: {e_inc}")
                    
                    field_value += f"{icon} - {name}{incident_msgs}\n"
                except Exception as e_mon:
                    print(f"DEBUG:   - Erreur moniteur {mon}: {e_mon}")

            if field_value:
                embed.add_field(name=page_title, value=field_value, inline=False)


        # Ajouter une légende pour les icônes
        embed.add_field(
            name="Légende:",
            value=(
                "<a:dh_online_bot:1369989959150206986> - Serveur en ligne\n"
                "<a:dh_warning_bot:1369990072690020472> - Serveur en attente\n"
                "<a:dh_offline_bot:1369990018633830401> - Serveur hors ligne\n"
                "<a:dh_maintenance_bot:1369989917756624987> - Serveur en maintenance\n"
            ),
            inline=False
        )

        embed.set_footer(text="Dernière mise à jour automatique")
        return embed

    @tasks.loop(minutes=5)
    async def auto_update(self):
        # Mise à jour automatique toutes les 60 secondes
        try:
            if self.message:
                embed = await self.create_embed()
                await self.message.edit(embed=embed)
            else:
                # Try to recover message if lost
                await self.cog_load()
        except Exception as e:
            error_trace = traceback.format_exc()
            print(f"Error in auto_update loop: {e}")
            # Log to DB
            query = "INSERT INTO bot_crashes (error_type, error_message, stack_trace, cog_name) VALUES (%s, %s, %s, %s)"
            await Database.execute(query, ("TaskLoopError", str(e), error_trace, "KenerEmbed"))

    @commands.command(name="status_refresh")
    @commands.has_permissions(administrator=True)
    async def status_refresh(self, ctx):
        """Force l'actualisation de l'embed de statut."""
        try:
            embed = await self.create_embed()
            if self.message:
                await self.message.edit(embed=embed)
                await ctx.send("✅ L'embed de statut a été actualisé avec succès !", delete_after=10)
            else:
                # Si le message n'est pas trouvé, on essaie de le recharger/recréer via cog_load
                await self.cog_load()
                if self.message:
                    await ctx.send("⚠️ Le message était manquant mais a été recréé et actualisé.", delete_after=10)
                else:
                    await ctx.send("❌ Impossible de trouver ou de créer le message de statut.", delete_after=10)
        except Exception as e:
            await ctx.send(f"❌ Une erreur est survenue : {e}", delete_after=10)
        finally:
            try:
                await ctx.message.delete()
            except:
                pass

    @auto_update.before_loop
    async def before_auto(self):
        # Attente que le bot soit prêt avant de démarrer la boucle
        await self.bot.wait_until_ready()

def setup(bot: commands.Bot):
    # Ajouter le cog au bot
    bot.add_cog(KenerEmbed(bot))
    print("KenerEmbed cog loaded.")

def teardown(bot: commands.Bot):
    # Supprimer le cog du bot
    bot.remove_cog("KenerEmbed")
    print("KenerEmbed cog unloaded.")
