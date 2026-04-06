import json
import requests
import disnake
from disnake.ext import commands, tasks
from datetime import datetime

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
        # Fonction générique pour récupérer des données de l'API Kener v4
        try:
            url = f"{API_URL}/api/v4/{endpoint}"
            response = requests.get(url, headers=HEADERS, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error fetching {endpoint}: {e}")
            # Retourner une liste vide pour les endpoints de type list, sinon un dictionnaire vide
            if any(x in endpoint for x in ["monitors", "incidents", "pages", "maintenances"]):
                return {}
            return {}

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

        # Ajouter chaque page et ses moniteurs à l'embed
        for page in pages:
            page_title = page.get("page_title", "Sans titre")
            # En v4, les moniteurs peuvent être des objets ou des tags
            mons = page.get("monitors", [])
            
            # FILTRAGE PAR CATÉGORIE (Optionnel, basé sur config)
            # Si on veut filtrer les pages qui pourraient être exclues via config
            if page_title in EXCLUDED_CATEGORIES:
                print(f"DEBUG: Page '{page_title}' exclue (config).")
                continue

            print(f"DEBUG: Page: {page_title} | Nombre de moniteurs : {len(mons)}")
            if not mons:
                continue
                
            field_value = ""
            for mon in mons:
                try:
                    # En v4, mon peut être un dict (v4 Swagger) ou un str (Kener v4 réel parfois)
                    if isinstance(mon, dict):
                        tag = mon.get("monitor_tag") or mon.get("tag")
                    else:
                        tag = str(mon)
                    
                    if not tag:
                        print(f"DEBUG:   - Moniteur ignoré : Pas de tag trouvé dans {mon}")
                        continue

                    # Récupérer les données complètes du moniteur depuis monitor_map
                    # On privilégie monitor_map (vrai statut), sinon ce qu'on a dans 'mon'
                    mon_data = monitor_map.get(tag) or (mon if isinstance(mon, dict) else {})
                    
                    name = mon_data.get("name") or tag
                    raw_status = mon_data.get("status") or "UP"
                    status = str(raw_status).upper()
                    
                    print(f"DEBUG:   - Moniteur: {name} (Tag: {tag}) | Status: {status}")
                    
                    # Icône en fonction du statut
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
