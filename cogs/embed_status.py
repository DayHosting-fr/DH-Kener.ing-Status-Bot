import json
import requests
import disnake
from disnake.ext import commands, tasks
from datetime import datetime

# Charger la configuration
with open("config.json") as f:
    configs = json.load(f)

API_URL = configs["KENER_API_URL"]
API_KEY = configs["KENER_API_KEY"]
CHANNEL_ID = configs["CHANNEL_ID"]
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

class KenerEmbed(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.channel = None
        self.message = None

    @commands.Cog.listener()
    async def on_ready(self):
        await self.bot.wait_until_ready()
        self.channel = self.bot.get_channel(int(CHANNEL_ID))
        if not self.channel:
            print(f"Channel ID {CHANNEL_ID} not found.")
            return

        try:
            with open("message_id.txt", "r") as f:
                msg_id = int(f.read().strip())
                self.message = await self.channel.fetch_message(msg_id)
        except Exception:
            embed = await self.create_embed()
            self.message = await self.channel.send(embed=embed)
            with open("message_id.txt", "w") as f:
                f.write(str(self.message.id))

        self.auto_update.start()

    async def fetch_data(self, endpoint, params=None):
        try:
            response = requests.get(f"{API_URL}/api/{endpoint}", headers=HEADERS, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching {endpoint}: {e}")
            return [] if "list" in endpoint else {}

    async def create_embed(self):
        embed = disnake.Embed(
            title=":satellite: État des serveurs",
            color=disnake.Color.blue(),
            timestamp=datetime.utcnow()
        )
        embed.set_author(name="DayHosting", icon_url=configs.get("AUTHOR_ICON"))
        embed.set_thumbnail(url=configs.get("THUMBNAIL_URL"))

        embed.description = ("Les status sur cette page sont actualisés toutes les 5 minutes. "
                            "\nUne version web est disponible [ici](https://status.dayhosting.fr)")

        monitors = await self.fetch_data("monitor")

        # ⚠️ Si on ne récupère pas les monitors, afficher le message d'erreur de la capture
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




        incidents = await self.fetch_data("incident", {"status": "OPEN"})

        monitor_map = {str(m["id"]): m for m in monitors}
        monitor_tags = {m["tag"]: str(m["id"]) for m in monitors}
        monitor_incidents = {str(m["id"]): [] for m in monitors}

        for incident in incidents:
            incident_id = incident["id"]
            state = incident.get("state", "")
            incident_type = incident.get("incident_type", "")
            title = incident.get("title", "Raison inconnue")

            impacted = await self.fetch_data(f"incident/{incident_id}/monitors")
            for mon in impacted:
                tag = mon["monitor_tag"]
                mon_id = monitor_tags.get(tag)
                if mon_id:
                    monitor_incidents[mon_id].append(incident)

        # Groupement par catégorie
        groups = {}
        for mon in monitors:
            for cat in mon.get("categories") or ["Sans catégorie"]:
                groups.setdefault(cat, []).append(mon)

        for group, mons in groups.items():
            field_value = ""
            for mon in mons:
                mon_id = str(mon["id"])
                tag = mon["tag"]
                name = mon["name"]
                status = (await self.fetch_data("status", {"tag": tag})).get("status", "?").upper()

                # Icône en fonction du statut
                icon = configs["STATUS_ICONS"].get(status, configs["STATUS_ICONS"].get("UNKNOWN"))

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
        if self.message:
            embed = await self.create_embed()
            await self.message.edit(embed=embed)

    @auto_update.before_loop
    async def before_auto(self):
        await self.bot.wait_until_ready()

def setup(bot: commands.Bot):
    bot.add_cog(KenerEmbed(bot))
    print("KenerEmbed cog loaded.")

def teardown(bot: commands.Bot):
    bot.remove_cog("KenerEmbed")
    print("KenerEmbed cog unloaded.")
