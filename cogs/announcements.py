import disnake
from disnake.ext import commands, tasks
from utils.database import Database
import datetime
import json

class Announcements(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_announcements.start()

    def cog_unload(self):
        self.check_announcements.cancel()

    @tasks.loop(minutes=1)
    async def check_announcements(self):
        """Checks DB for pending announcements and sends them."""
        now = datetime.datetime.now()
        query = "SELECT id, channel_id, message, embed_json FROM scheduled_announcements WHERE scheduled_at <= %s AND sent = FALSE"
        rows = await Database.execute(query, (now,))
        
        for row in rows:
            ann_id, channel_id, message, embed_json = row
            channel = self.bot.get_channel(channel_id)
            if channel:
                try:
                    embed = None
                    if embed_json:
                        data = json.loads(embed_json)
                        embed = disnake.Embed.from_dict(data)
                    
                    await channel.send(content=message, embed=embed)
                    await Database.execute("UPDATE scheduled_announcements SET sent = TRUE WHERE id = %s", (ann_id,))
                except Exception as e:
                    print(f"Error sending scheduled announcement {ann_id}: {e}")
            else:
                print(f"Channel {channel_id} not found for announcement {ann_id}")

    @commands.slash_command(name="announce")
    async def announce(self, inter):
        pass

    @announce.sub_command(name="schedule", description="Programmer une annonce")
    async def schedule(
        self, 
        inter: disnake.ApplicationCommandInteraction, 
        channel: disnake.TextChannel, 
        message: str, 
        date_time: str, # Format: "YYYY-MM-DD HH:MM"
        title: str = None,
        color: str = "00ff00"
    ):
        try:
            scheduled_at = datetime.datetime.strptime(date_time, "%Y-%m-%d %H:%M")
        except ValueError:
            return await inter.response.send_message("Format de date invalide. Utilisez YYYY-MM-DD HH:MM", ephemeral=True)

        embed_json = None
        if title:
            embed = disnake.Embed(title=title, description=message, color=int(color, 16))
            embed_json = json.dumps(embed.to_dict())
            message = "" # If we have an embed, the message becomes the content or is empty

        query = "INSERT INTO scheduled_announcements (channel_id, message, embed_json, scheduled_at) VALUES (%s, %s, %s, %s)"
        await Database.execute(query, (channel.id, message, embed_json, scheduled_at))
        
        await inter.response.send_message(f"Annonce programmée pour {date_time} dans {channel.mention}", ephemeral=True)

    @announce.sub_command(name="list", description="Liste les annonces programmées")
    async def list_announcements(self, inter):
        query = "SELECT id, channel_id, scheduled_at FROM scheduled_announcements WHERE sent = FALSE ORDER BY scheduled_at ASC"
        rows = await Database.execute(query)
        
        if not rows:
            return await inter.response.send_message("Aucune annonce programmée.", ephemeral=True)
        
        text = "**Annonces en attente :**\n"
        for row in rows:
            ann_id, channel_id, scheduled_at = row
            text += f"ID: {ann_id} | Salon: <#{channel_id}> | Date: {scheduled_at}\n"
        
        await inter.response.send_message(text, ephemeral=True)

    @announce.sub_command(name="remove", description="Supprime une annonce programmée")
    async def remove(self, inter, announcement_id: int):
        await Database.execute("DELETE FROM scheduled_announcements WHERE id = %s", (announcement_id,))
        await inter.response.send_message(f"Annonce {announcement_id} supprimée.", ephemeral=True)

def setup(bot: commands.Bot):
    bot.add_cog(Announcements(bot))
    print("Announcements cog is loaded")
