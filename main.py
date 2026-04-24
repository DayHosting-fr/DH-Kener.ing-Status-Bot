import disnake, os, json, traceback, asyncio, logging
from disnake.ext import commands, tasks
from utils.database import Database
from datetime import datetime, timedelta
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# Setup Logging for Dashboard
class DashboardLogHandler(logging.Handler):
    def __init__(self, capacity=100):
        super().__init__()
        self.capacity = capacity
        self.logs = []

    def emit(self, record):
        log_entry = self.format(record)
        self.logs.append({
            "timestamp": datetime.now().isoformat(),
            "level": record.levelname,
            "message": log_entry
        })
        if len(self.logs) > self.capacity:
            self.logs.pop(0)

log_handler = DashboardLogHandler()
log_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(log_handler)
logging.getLogger().setLevel(logging.INFO)

intents = disnake.Intents.all()

with open('config.json', encoding="utf-8") as f:
    configs = json.load(f)

activity = disnake.Activity(
    name=configs["ACTIVITY_NAME"],
    type=disnake.ActivityType.watching
)

bot = commands.Bot(
    command_prefix=configs["COMMAND_PREFIX"],
    intents=intents,
    activity=activity)
bot.help_command = None
# Loading Cogs for the first time
async def load_cogs():
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py'):
            try:
                bot.load_extension(f'cogs.{filename[:-3]}')
            except Exception as e:
                print(f"Failed to load extension {filename}: {e}")

@tasks.loop(minutes=5)
async def monitor_cogs():
    """Checks if critical cogs are loaded and reloads if necessary."""
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py'):
            cog_name = f'cogs.{filename[:-3]}'
            if cog_name not in bot.extensions:
                try:
                    bot.load_extension(cog_name)
                    print(f"Auto-recovered cog: {cog_name}")
                except Exception as e:
                    await log_crash("CogLoader", str(e), traceback.format_exc(), cog_name)

@tasks.loop(hours=1)
async def track_stats():
    """Logs member count for analytics."""
    for guild in bot.guilds:
        await Database.execute(
            "INSERT INTO member_stats (guild_id, member_count) VALUES (%s, %s)",
            (guild.id, guild.member_count)
        )

async def log_crash(error_type, message, trace, cog=None):
    query = "INSERT INTO bot_crashes (error_type, error_message, stack_trace, cog_name) VALUES (%s, %s, %s, %s)"
    await Database.execute(query, (error_type, message, trace, cog))
    # Alert without spamming (simple check: if last error was same, skip?)
    # For now, just logging to DB.

# Here is all the command for admins to load, unload and reload cogs
@bot.command()
@commands.has_permissions(administrator=True)
async def reload(ctx, extension):
    bot.reload_extension(f'cogs.{extension}')
    await ctx.message.delete()
    await ctx.send(f'{extension} reloaded', delete_after=5)

@bot.command()
@commands.has_permissions(administrator=True)
async def load(ctx, extension):
    bot.load_extension(f'cogs.{extension}')
    await ctx.message.delete()
    await ctx.send(f'{extension} loaded', delete_after=5)

@bot.command()
@commands.has_permissions(administrator=True)
async def unload(ctx, extension):
    bot.unload_extension(f'cogs.{extension}')
    await ctx.message.delete()
    await ctx.send(f'{extension} unloaded', delete_after=5)

@bot.event
async def on_ready():
    print(f'Bot is ready. Logged in as {bot.user}')
    await load_cogs()
    monitor_cogs.start()
    track_stats.start()

@bot.event
async def on_error(event, *args, **kwargs):
    error_message = traceback.format_exc()
    print(f"ERROR in {event}: {error_message}")
    await log_crash("GlobalEvent", str(event), error_message)

@bot.event
async def on_slash_command_error(inter, error):
    error_message = traceback.format_exc()
    await log_crash("SlashCommand", str(error), error_message, inter.application_command.name)
    if not inter.response.is_done():
        await inter.response.send_message(f"Une erreur est survenue : {error}", ephemeral=True)
    else:
        await inter.followup.send(f"Une erreur est survenue : {error}", ephemeral=True)

def generate_self_signed_cert(cert_path, key_path):
    """Generates a self-signed certificate for local HTTPS development."""
    print("Generating self-signed SSL certificate...")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "FR"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "France"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Chancenay"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "DayHosting"),
        x509.NameAttribute(NameOID.COMMON_NAME, "node02.dayhosting.fr"),
    ])
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.utcnow()
    ).not_valid_after(
        datetime.utcnow() + timedelta(days=365)
    ).add_extension(
        x509.SubjectAlternativeName([x509.DNSName("node02.dayhosting.fr")]),
        critical=False,
    ).sign(key, hashes.SHA256())

    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(key_path, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
    print(f"SSL Certificates generated: {cert_path}, {key_path}")

async def main():
    # Start Dashboard
    from dashboard.main import app as dashboard_app
    import dashboard.main as dashboard_module
    dashboard_module.bot = bot
    dashboard_module.log_handler = log_handler
    import uvicorn
    import os
    
    # SSL Check
    ssl_cert = "cert.pem"
    ssl_key = "key.pem"
    
    if not os.path.exists(ssl_cert) or not os.path.exists(ssl_key):
        generate_self_signed_cert(ssl_cert, ssl_key)
        
    print("Starting dashboard in HTTPS mode.")
    ssl_args = {
        "ssl_certfile": ssl_cert,
        "ssl_keyfile": ssl_key
    }

    config_uvicorn = uvicorn.Config(
        dashboard_app, 
        host="0.0.0.0", 
        port=configs['DASHBOARD']['PORT'], 
        log_level="info",
        **ssl_args
    )
    server = uvicorn.Server(config_uvicorn)
    
    # Run both
    await asyncio.gather(
        server.serve(),
        bot.start(configs["DISCORD_BOT_TOKEN"])
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
