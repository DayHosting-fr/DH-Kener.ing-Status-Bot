from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
import json, httpx, datetime
from pydantic import BaseModel
from utils.database import Database

class AnnouncementCreate(BaseModel):
    channel_id: int
    message: str
    scheduled_at: str

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

@app.get("/stats")
async def stats_page(request: Request):
    user = request.session.get("user")
    if not user: return RedirectResponse("/")
    return templates.TemplateResponse("stats.html", {"request": request, "user": user, "active_page": "stats"})

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
        
    return {
        "status": status,
        "crashes_last_12h": crash_count,
        "timestamp": datetime.datetime.now().isoformat()
    }

@app.get("/api/stats")
async def stats():
    # Example stats
    q1 = "SELECT COUNT(*) FROM scheduled_announcements WHERE sent = FALSE"
    q2 = "SELECT COUNT(*) FROM bot_crashes"
    r1 = await Database.execute(q1)
    r2 = await Database.execute(q2)
    return {
        "pending_announcements": r1[0][0],
        "total_crashes": r2[0][0]
    }

@app.get("/api/announcements")
async def get_announcements():
    query = "SELECT id, channel_id, scheduled_at, sent, message FROM scheduled_announcements ORDER BY scheduled_at DESC LIMIT 50"
    rows = await Database.execute(query)
    return [
        {"id": r[0], "channel_id": r[1], "scheduled_at": r[2].isoformat(), "sent": bool(r[3]), "message": r[4]}
        for r in rows
    ]

@app.get("/api/logs")
async def get_logs():
    query = "SELECT staff_id, action, details, timestamp FROM staff_logs ORDER BY timestamp DESC LIMIT 50"
    rows = await Database.execute(query)
    return [
        {"staff_id": r[0], "action": r[1], "details": r[2], "timestamp": r[3].isoformat()}
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config['DASHBOARD']['PORT'])
