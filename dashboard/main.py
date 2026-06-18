from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
import json, httpx, datetime
from pydantic import BaseModel
from typing import List
from utils.database import Database
import os

# Dashboard Cache System
CACHE_FILE = "dashboard_cache.json"
DASHBOARD_CACHE = {
    "current_members": 0,
    "total_crashes": 0,
    "history": [],
    "last_update": None
}

def load_cache():
    global DASHBOARD_CACHE
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                DASHBOARD_CACHE.update(json.load(f))
        except: pass

def save_cache():
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(DASHBOARD_CACHE, f)
    except: pass

load_cache()

class AnnouncementCreate(BaseModel):
    channel_id: int
    message: str
    scheduled_at: str

class AutoResponseCreate(BaseModel):
    trigger: str
    response: str
    is_exact: bool

class ExclusionsUpdate(BaseModel):
    channels: List[str]

bot = None # Set by main.py
log_handler = None # Set by main.py

with open('config.json', encoding="utf-8") as f:
    config = json.load(f)

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=config['DASHBOARD']['SESSION_SECRET'])
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
app.mount("/static", StaticFiles(directory="dashboard/static"), name="static")
templates = Jinja2Templates(directory="dashboard/templates")

CLIENT_ID = config['DASHBOARD']['CLIENT_ID']
CLIENT_SECRET = config['DASHBOARD']['CLIENT_SECRET']
REDIRECT_URI = f"{config['DASHBOARD']['URL']}/callback"
ROLE_ID = config['DASHBOARD']['ROLE_ID']

@app.get("/")
async def root(request: Request):
    user = request.session.get("user")
    if not user:
        return templates.TemplateResponse("login.html", {"request": request})
    
    if not await check_user_role(request.session.get("access_token")):
        request.session.clear()
        return HTMLResponse("Accès refusé : Vous n'avez pas le rôle requis.", status_code=403)
    
    return templates.TemplateResponse("index.html", {"request": request, "user": user, "active_page": "home"})

@app.get("/announcements")
async def announcements_page(request: Request):
    user = request.session.get("user")
    if not user: return RedirectResponse("/")
    return templates.TemplateResponse("announcements.html", {"request": request, "user": user, "active_page": "announcements"})

@app.get("/logs")
async def logs_page(request: Request):
    user = request.session.get("user")
    if not user: return RedirectResponse("/")
    return templates.TemplateResponse("logs.html", {"request": request, "user": user, "active_page": "logs"})

@app.get("/console")
async def console_page(request: Request):
    user = request.session.get("user")
    if not user: return RedirectResponse("/")
    return templates.TemplateResponse("console.html", {"request": request, "user": user, "active_page": "console"})

@app.get("/stats")
async def stats_page(request: Request):
    user = request.session.get("user")
    if not user: return RedirectResponse("/")
    return templates.TemplateResponse("stats.html", {"request": request, "user": user, "active_page": "stats"})

@app.get("/auto-responder")
async def auto_responder_page(request: Request):
    user = request.session.get("user")
    if not user: return RedirectResponse("/")
    return templates.TemplateResponse("auto_responder.html", {"request": request, "user": user, "active_page": "auto_responder"})

@app.get("/login")
async def login():
    return RedirectResponse(
        f"https://discord.com/api/oauth2/authorize?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&scope=identify guilds.members.read"
    )

@app.get("/callback")
async def callback(request: Request, code: str):
    async with httpx.AsyncClient() as client:
        # Get token
        data = {
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': REDIRECT_URI
        }
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        response = await client.post("https://discord.com/api/oauth2/token", data=data, headers=headers)
        tokens = response.json()
        access_token = tokens.get("access_token")
        
        # Get user info
        headers = {'Authorization': f'Bearer {access_token}'}
        user_response = await client.get("https://discord.com/api/users/@me", headers=headers)
        user_data = user_response.json()
        
        request.session["user"] = user_data
        request.session["access_token"] = access_token
        
    return RedirectResponse("/")

async def check_user_role(access_token):
    # This bot is for a specific guild, we should know the guild id.
    # In this case, we check if the user has the role in the guild provided in config.
    # Assuming guild ID is from the bot's config or inferred.
    # For now, let's look at the config.json for GUILD_ID if it exists, or use a default.
    # Adding GUILD_ID to config might be better. 
    # For this task, I'll bypass the strict guild check if not available, 
    # but the user specified "role id", so I must check it.
    
    # Use the Guild ID from config.json
    guild_id = config.get("GUILD_ID")
    
    async with httpx.AsyncClient() as client:
        headers = {'Authorization': f'Bearer {access_token}'}
        # Get user member info for the guild
        resp = await client.get(f"https://discord.com/api/users/@me/guilds/{guild_id}/member", headers=headers)
        if resp.status_code == 200:
            member_data = resp.json()
            roles = member_data.get("roles", [])
            return str(ROLE_ID) in roles
    return False

@app.get("/api/health")
async def health():
    # Check crashes in the last 12 hours
    twelve_hours_ago = datetime.datetime.now() - datetime.timedelta(hours=12)
    query = "SELECT COUNT(*) FROM bot_crashes WHERE timestamp >= %s"
    res = await Database.execute(query, (twelve_hours_ago,))
    crash_count = res[0][0]
    
    status = "Healthy"
    if crash_count > 5:
        status = "Degraded"
    if crash_count > 20:
        status = "Down"
    
    DASHBOARD_CACHE["status"] = status
    DASHBOARD_CACHE["crashes_last_12h"] = crash_count
    save_cache()
         
    return {
        "status": status,
        "crashes_last_12h": crash_count,
        "timestamp": datetime.datetime.now().isoformat()
    }

@app.get("/api/stats")
async def stats():
    global DASHBOARD_CACHE
    # Try to get live data
    member_count = DASHBOARD_CACHE["current_members"]
    is_live = False
    
    if bot:
        guild = bot.get_guild(config.get("GUILD_ID"))
        if guild:
            member_count = guild.member_count
            DASHBOARD_CACHE["current_members"] = member_count
            is_live = True

    q2 = "SELECT COUNT(*) FROM bot_crashes"
    r2 = await Database.execute(q2)
    total_crashes = r2[0][0] if r2 else DASHBOARD_CACHE["total_crashes"]
    DASHBOARD_CACHE["total_crashes"] = total_crashes
    
    # Get history for the last 7 entries
    q3 = "SELECT member_count, timestamp FROM member_stats ORDER BY timestamp DESC LIMIT 7"
    r3 = await Database.execute(q3)
    if r3:
        history = [{"count": r[0], "time": r[1].isoformat()} for r in r3]
        DASHBOARD_CACHE["history"] = history[::-1]
    
    DASHBOARD_CACHE["last_update"] = datetime.datetime.now().isoformat()
    save_cache()
    
    return {
        "current_members": member_count,
        "total_crashes": total_crashes,
        "history": DASHBOARD_CACHE["history"],
        "last_update": DASHBOARD_CACHE["last_update"],
        "is_live": is_live
    }

@app.get("/api/announcements")
async def get_announcements():
    try:
        query = "SELECT id, channel_id, scheduled_at, sent, message FROM scheduled_announcements ORDER BY scheduled_at DESC LIMIT 50"
        rows = await Database.execute(query)
        return [
            {"id": r[0], "channel_id": str(r[1]), "scheduled_at": r[2].isoformat(), "sent": bool(r[3]), "message": r[4]}
            for r in rows
        ]
    except Exception as e:
        print(f"Error in get_announcements: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/logs")
async def get_logs():
    query = "SELECT staff_id, action, details, timestamp FROM staff_logs ORDER BY timestamp DESC LIMIT 50"
    rows = await Database.execute(query)
    return [
        {"staff_id": str(r[0]), "action": r[1], "details": r[2], "timestamp": r[3].isoformat()}
        for r in rows
    ]

@app.post("/api/announcements")
async def create_announcement(data: AnnouncementCreate):
    try:
        # Standardize date format from frontend (YYYY-MM-DD HH:MM)
        dt = datetime.datetime.strptime(data.scheduled_at, "%Y-%m-%d %H:%M")
        query = "INSERT INTO scheduled_announcements (channel_id, message, scheduled_at) VALUES (%s, %s, %s)"
        await Database.execute(query, (data.channel_id, data.message, dt))
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/api/announcements/{id}")
async def update_announcement(id: int, data: AnnouncementCreate):
    try:
        dt = datetime.datetime.strptime(data.scheduled_at, "%Y-%m-%d %H:%M")
        query = "UPDATE scheduled_announcements SET channel_id = %s, message = %s, scheduled_at = %s WHERE id = %s"
        await Database.execute(query, (data.channel_id, data.message, dt, id))
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/announcements/{id}")
async def delete_announcement(id: int):
    try:
        query = "DELETE FROM scheduled_announcements WHERE id = %s"
        await Database.execute(query, (id,))
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/guild/roles")
async def get_roles():
    if not bot: return []
    guild = bot.get_guild(config.get("GUILD_ID"))
    if not guild: return []
    return [{"id": str(r.id), "name": r.name, "color": str(r.color)} for r in guild.roles if not r.is_default()]

@app.get("/api/guild/emojis")
async def get_emojis():
    if not bot: return []
    guild = bot.get_guild(config.get("GUILD_ID"))
    if not guild: return []
    return [{"id": str(e.id), "name": e.name, "url": str(e.url), "animated": e.animated} for e in guild.emojis]

@app.get("/api/guild/channels")
async def get_channels():
    if not bot: return []
    guild = bot.get_guild(config.get("GUILD_ID"))
    if not guild: return []
    return [{"id": str(c.id), "name": c.name} for c in guild.text_channels]

@app.get("/api/console/logs")
async def get_console_logs():
    if not log_handler: return []
    return log_handler.logs

@app.get("/api/auto-responses")
async def get_auto_responses():
    try:
        query = "SELECT id, trigger_word, response_text, is_exact FROM auto_responses ORDER BY id DESC"
        rows = await Database.execute(query)
        return [{"id": r[0], "trigger": r[1], "response": r[2], "is_exact": bool(r[3])} for r in rows]
    except Exception as e:
        print(f"Error in get_auto_responses: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/auto-responses")
async def create_auto_response(data: AutoResponseCreate):
    query = "INSERT INTO auto_responses (trigger_word, response_text, is_exact) VALUES (%s, %s, %s)"
    await Database.execute(query, (data.trigger, data.response, data.is_exact))
    if bot:
        cog = bot.get_cog("AutoResponder")
        if cog: await cog.load_responses()
    return {"status": "success"}

@app.delete("/api/auto-responses/{id}")
async def delete_auto_response(id: int):
    query = "DELETE FROM auto_responses WHERE id = %s"
    await Database.execute(query, (id,))
    if bot:
        cog = bot.get_cog("AutoResponder")
        if cog: await cog.load_responses()
    return {"status": "success"}

@app.get("/api/auto-responses/exclusions")
async def get_exclusions():
    with open('config.json', encoding="utf-8") as f:
        conf = json.load(f)
    exclusions = conf.get("AUTO_RESPONDER_EXCLUDED_CHANNELS", [])
    return [str(id) for id in exclusions]

@app.post("/api/auto-responses/exclusions")
async def set_exclusions(data: ExclusionsUpdate):
    with open('config.json', encoding="utf-8") as f:
        conf = json.load(f)
    conf["AUTO_RESPONDER_EXCLUDED_CHANNELS"] = data.channels
    with open('config.json', 'w', encoding="utf-8") as f:
        json.dump(conf, f, indent=2)
    return {"status": "success"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config['DASHBOARD']['PORT'])
