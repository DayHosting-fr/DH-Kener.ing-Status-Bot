import disnake
from disnake.ext import commands
from utils.database import Database

class AutoResponder(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.responses = []
        self.bot.loop.create_task(self.load_responses())

    async def load_responses(self):
        try:
            query = "SELECT trigger_word, response_text, is_exact FROM auto_responses"
            rows = await Database.execute(query)
            self.responses = [{"trigger": r[0].lower(), "text": r[1], "exact": bool(r[2])} for r in rows]
            print(f"Loaded {len(self.responses)} auto-responses.")
        except Exception as e:
            print(f"Error loading auto-responses: {e}")

    @commands.Cog.listener()
    async def on_message(self, message: disnake.Message):
        if message.author.bot:
            return

        # Check excluded channels
        try:
            with open("config.json", encoding="utf-8") as f:
                config = json.load(f)
            excluded_channels = config.get("AUTO_RESPONDER_EXCLUDED_CHANNELS", [])
            if message.channel.id in excluded_channels or str(message.channel.id) in [str(id) for id in excluded_channels]:
                return
        except:
            pass

        # Skip if it's a command
        prefix = self.bot.command_prefix
        if message.content.startswith(prefix):
            return

        content = message.content.lower()
        for res in self.responses:
            if res["exact"]:
                if content == res["trigger"]:
                    await message.channel.send(res["text"])
                    return # Only one response per message
            else:
                if res["trigger"] in content:
                    await message.channel.send(res["text"])
                    return

    @commands.command(name="reload_responses")
    @commands.has_permissions(administrator=True)
    async def reload_responses(self, ctx):
        await self.load_responses()
        await ctx.send("✅ Auto-responses rechargées depuis la base de données !", delete_after=5)
        try: await ctx.message.delete()
        except: pass

def setup(bot: commands.Bot):
    bot.add_cog(AutoResponder(bot))
