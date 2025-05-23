import json
import requests
import disnake
from disnake.ext import commands, tasks
from datetime import datetime

# Charger la configuration depuis le fichier 'config.json'
with open("config.json") as f:
    configs = json.load(f)

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
            for cat in mon.get("categories") or ["Sans catégorie"]:
                groups.setdefault(cat, []).append(mon)

        # Ajouter chaque groupe et ses moniteurs à l'embed
        for group, mons in groups.items():
            field_value = ""
            for mon in mons:
                mon_id = str(mon["id"])
                tag = mon["tag"]
                name = mon["name"]
                status = (await self.fetch_data("status", {"tag": tag})).get("status", "?").upper()

                # Icône en fonction du statut
                icon = configs["STATUS_ICONS"].get(status, configs["STATUS_ICONS"].get("UNKNOWN"))

                # Ajouter des messages pour chaque incident lié au moniteur
                incident_msgs = ""
                for inc in monitor_incidents[mon_id]:
                    inc_type = inc.get("incident_type")
                    reason = inc.get("title", "Raison inconnue")
                    updates = await self.fetch_data(f"incident/{inc['id']}/updates")
                    desc = updates[0].get("comment") if updates else None
                    desc_text = f"\n   Description : `{desc}`" if desc else ""

                    if inc_type != "MAINTENANCE":
                        incident_msgs += f"\n   ⚠️ Incident - Raison : `{reason}`{desc_text}\n"
                    
                field_value += f"{icon} - {name}{incident_msgs}\n"

            embed.add_field(name=group, value=field_value or "Aucun monitor", inline=False)

        # Ajouter une légende pour les icônes
        embed.add_field(
            name="Légende:",
            value=(
                "<a:online:1237966542352945192> - Serveur en ligne\n"
                "<a:warning:1237966536212349010> - Serveur en attente\n"
                "<a:offline:1237966540519768144> - Serveur hors ligne\n"
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
