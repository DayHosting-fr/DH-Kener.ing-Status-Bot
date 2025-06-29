import json
import requests
import disnake
from disnake.ext import commands, tasks
from datetime import datetime

# Charger la configuration depuis le fichier 'config.json'
with open("config.json") as f:
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

    @commands.Cog.listener()
    async def on_ready(self):
        # Attente que le bot soit prêt avant de configurer le canal et le message
        await self.bot.wait_until_ready()
        self.channel = self.bot.get_channel(int(CHANNEL_ID))
        
        if not self.channel:
            print(f"Channel ID {CHANNEL_ID} not found.")
            return

        # Tentative de récupérer le message existant avec l'ID
        try:
            with open("message_id.txt", "r") as f:
                msg_id = int(f.read().strip())
                self.message = await self.channel.fetch_message(msg_id)
        except Exception:
            # Si le message n'existe pas, on crée un nouveau message
            embed = await self.create_embed()
            self.message = await self.channel.send(embed=embed)
            # Sauvegarder l'ID du message pour les mises à jour futures
            with open("message_id.txt", "w") as f:
                f.write(str(self.message.id))

        # Démarrer le processus de mise à jour automatique toutes les minutes
        self.auto_update.start()

    async def fetch_data(self, endpoint, params=None):
        # Fonction générique pour récupérer des données de l'API Kener
        try:
            response = requests.get(f"{API_URL}/api/{endpoint}", headers=HEADERS, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching {endpoint}: {e}")
            return [] if "list" in endpoint else {}

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

        # Récupérer la liste des moniteurs
        monitors = await self.fetch_data("monitor")

        # Si aucune donnée n'est récupérée pour les moniteurs, afficher un message d'erreur
        if not monitors:
            embed = disnake.Embed(
                title="Status des serveurs",
                description=("Une erreur est survenue avec la connexion à notre serveur de status, "
                             "merci de patienter quelques instants ou de contacter un <@&841787186558926898> - "
                             "[Membre de l'équipe](https://discord.gg/6smzrQ6bN2)."),
                color=disnake.Color.red(),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text=datetime.utcnow())
            return embed

        # Récupérer les incidents ouverts
        incidents = await self.fetch_data("incident", {"status": "OPEN"})

        # Créer une cartographie des moniteurs pour un accès rapide
        monitor_map = {str(m["id"]): m for m in monitors}
        monitor_tags = {m["tag"]: str(m["id"]) for m in monitors}
        monitor_incidents = {str(m["id"]): [] for m in monitors}

        # Organiser les incidents par moniteur
        for incident in incidents:
            incident_id = incident["id"]
            impacted = await self.fetch_data(f"incident/{incident_id}/monitors")
            for mon in impacted:
                tag = mon["monitor_tag"]
                mon_id = monitor_tags.get(tag)
                if mon_id:
                    monitor_incidents[mon_id].append(incident)

        # Grouper les moniteurs par catégorie
        groups = {}
        for mon in monitors:
            category_name = mon.get("category_name")
            categories = [category_name] if isinstance(category_name, str) else category_name or ["Sans catégorie"]
            for cat in categories:
                groups.setdefault(cat, []).append(mon)

        # Ajouter chaque groupe et ses moniteurs à l'embed
        for group, mons in groups.items():
            if group in EXCLUDED_CATEGORIES:
                continue
            if group == "Home":
                group = "🔔Général"
            field_value = ""
            for mon in mons:
                tag = mon["tag"]
                if mon.get("category_name") in EXCLUDED_CATEGORIES:
                    continue
                mon_id = str(mon["id"])
                name = mon["name"]
                status = (await self.fetch_data("status", {"tag": tag})).get("status", "?").upper()

                # Icône en fonction du statut
                icon = configs["STATUS_ICONS"].get(status, configs["STATUS_ICONS"].get("UNKNOWN"))

                # Ajouter des messages pour chaque incident lié au moniteur
                incident_msgs = ""
                for inc in monitor_incidents[mon_id]:
                    if inc.get("state") == "RESOLVED" and inc.get("incident_type") != "MAINTENANCE":
                        continue
                    inc_type = inc.get("incident_type")
                    reason = inc.get("title", "Raison inconnue")
                    STATE = inc.get("state", "Incident").upper()
                    if STATE == "INVESTIGATING":
                        STATE_text = "⚠️ En cours d'investigation"
                    elif STATE == "IDENTIFIED":
                        STATE_text = "🔍 Identifié"
                    elif STATE == "MONITORING":
                        STATE_text = "👀 En cours de surveillance"
                    elif inc_type == "MAINTENANCE":
                        STATE_text = "🔧 En maintenance"

                    if STATE != "RESOLVED":
                        incident_msgs += f"\n   {STATE_text} - Raison : `{reason}`\n"

                    if inc_type == "MAINTENANCE":
                        end_time = inc.get("end_date_time")
                        if end_time and datetime.utcnow().timestamp() > end_time:
                            continue
                        incident_msgs += f"\n   {STATE_text} - Raison : `{reason}`\n"
                        icon = configs["STATUS_ICONS"].get("MAINTENANCE", configs["STATUS_ICONS"].get("UNKNOWN"))
                    
                field_value += f"{icon} - {name}{incident_msgs}\n"

            embed.add_field(name=group, value=field_value or "Aucun monitor", inline=False)

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

    @tasks.loop(seconds=60)
    async def auto_update(self):
        # Mise à jour automatique toutes les 60 secondes
        if self.message:
            embed = await self.create_embed()
            await self.message.edit(embed=embed)

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
