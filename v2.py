# v2.py
import os
import discord
from discord import app_commands, Interaction, ui
from discord.ext import commands
import httpx
import json
import asyncio
from typing import Optional
from dotenv import load_dotenv

# Load environment (you can instead hardcode or read from a config file)
load_dotenv()
DISCORD_TOKEN = "DISCORD_TOKEN"  # Discord bot token
PTERO_API_KEY = os.getenv("PTERO_API_KEY")  # Pterodactyl Application API key
PTERO_BASE = "https://dragoncloud.godanime.net" # Panel base URL

ADMIN_WHITELIST_FILE = "admin_whitelist.txt"

# HTTP headers for Pterodactyl Application API
DEFAULT_HEADERS = {
    "Authorization": f"Bearer {PTERO_API_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# Helper: admin persistence
def is_admin_raw(user_id: int) -> bool:
    if not os.path.isfile(ADMIN_WHITELIST_FILE):
        return False
    with open(ADMIN_WHITELIST_FILE, "r") as f:
        return str(user_id) in {line.strip() for line in f if line.strip()}

def add_admin_raw(user_id: int) -> bool:
    existing = set()
    if os.path.isfile(ADMIN_WHITELIST_FILE):
        with open(ADMIN_WHITELIST_FILE, "r") as f:
            existing = {line.strip() for line in f if line.strip()}
    if str(user_id) in existing:
        return False
    with open(ADMIN_WHITELIST_FILE, "a") as f:
        f.write(f"{user_id}\n")
    return True

# Async Pterodactyl Application API wrapper
async def ptero_request(method: str, path: str, json_body=None):
    url = f"{PTERO_BASE}/api/application{path}"
    async with httpx.AsyncClient(verify=False, timeout=30) as client:
        resp = await client.request(method, url, headers=DEFAULT_HEADERS, json=json_body)
        resp.raise_for_status()
        return resp.json()

def format_resources(server_attr: dict) -> str:
    limits = server_attr.get("limits", {})
    usage = server_attr.get("resources", {})
    # memory_bytes may not be present; some panels report differently—adjust if needed.
    ram_used = usage.get("memory_bytes", 0) / (1024 ** 3) if usage.get("memory_bytes") else 0
    ram_limit = limits.get("memory", 0) / 1024  # memory is in MB
    disk_used = usage.get("disk_bytes", 0) / (1024 ** 3) if usage.get("disk_bytes") else 0
    disk_limit = limits.get("disk", 0) / 1024
    cpu_percent = usage.get("cpu_absolute", 0)
    return (f"RAM: {ram_used:.2f}GB/{ram_limit:.2f}GB • "
            f"CPU: {cpu_percent:.1f}% • "
            f"Disk: {disk_used:.2f}GB/{disk_limit:.2f}GB")

# Discord bot setup (hybrid: prefix + slash)
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents, help_command=commands.MinimalHelpCommand())
tree = bot.tree  # alias

# Admin check decorator for commands.py style
def admin_check(ctx):
    return is_admin_raw(ctx.author.id)

# Slash admin check helper
def is_admin_interaction(user: discord.User) -> bool:
    return is_admin_raw(user.id)

@bot.event
async def on_ready():
    try:
        await tree.sync()
    except Exception:
        pass
    print(f"[READY] Logged in as {bot.user} ({bot.user.id})")

# PREFIX COMMANDS (fallback)
@bot.command(name="addadmin_bot")
@commands.check(admin_check)
async def addadmin_bot_prefix(ctx, userid: str):
    added = add_admin_raw(int(userid))
    if added:
        await ctx.reply(f"Added {userid} to admin whitelist.")
    else:
        await ctx.reply(f"{userid} was already an admin.")

@bot.command(name="create_acc")
@commands.check(admin_check)
async def create_acc_prefix(ctx, userid: str, email: str, password: str):
    await ctx.reply("Creating account...", ephemeral=True)
    try:
        payload = {
            "email": email,
            "username": f"user{userid}",
            "first_name": "User",
            "last_name": userid,
            "password": password,
            "language": "en"
        }
        resp = await ptero_request("POST", "/users", json_body=payload)
        # DM credentials
        try:
            member = await ctx.guild.fetch_member(int(userid))
            await member.send(f"Account created.\nEmail: {email}\nPassword: {password}\nPanel: {PTERO_BASE}")
            await ctx.reply(f"Created account and sent credentials to <@{userid}>.")
        except Exception:
            await ctx.reply(f"Account created. Credentials:\nEmail: {email}\nPassword: {password}\nPanel: {PTERO_BASE}")
    except Exception as e:
        await ctx.reply(f"Failed to create account: {e}")

@bot.command(name="create_server")
@commands.check(admin_check)
async def create_server_prefix(ctx, server_name: str, owner_email: str, cpu_limit: int, memory_mb: int, disk_mb: int):
    await ctx.reply("Creating server...", ephemeral=True)
    try:
        users_resp = await ptero_request("GET", f"/users?filter[email]={owner_email}")
        if not users_resp.get("data"):
            await ctx.reply(f"No panel user with email {owner_email}.")
            return
        user_id = users_resp["data"][0]["attributes"]["id"]
        # Replace nest/egg with your real IDs for Paper
        server_payload = {
            "name": server_name,
            "user": user_id,
            "nest": 1,  # <<-- placeholder
            "egg": 7,   # <<-- placeholder for Paper egg
            "docker_image": "ghcr.io/pterodactyl/yolks:java_17",
            "startup": "java -Xms128M -Xmx{{SERVER_MEMORY}}M -jar paper.jar",
            "limits": {
                "memory": memory_mb,
                "swap": 0,
                "disk": disk_mb,
                "io": 500,
                "cpu": cpu_limit
            },
            "feature_limits": {
                "databases": 1,
                "allocations": 1
            },
            "environment": {
                "PAPER_VERSION": "latest"
            }
        }
        created = await ptero_request("POST", "/servers", json_body=server_payload)
        identifier = created["attributes"]["identifier"]
        await ctx.reply(f"Server created: {server_name} (ID: {identifier})")
    except Exception as e:
        await ctx.reply(f"Error: {e}")

@bot.command(name="remove_server")
@commands.check(admin_check)
async def remove_server_prefix(ctx, serverid: str):
    await ctx.reply(f"Deleting server {serverid}...", ephemeral=True)
    try:
        await ptero_request("DELETE", f"/servers/{serverid}")
        await ctx.reply(f"Deleted server {serverid}.")
    except Exception as e:
        await ctx.reply(f"Failed to delete: {e}")

@bot.command(name="check_server_list")
@commands.check(admin_check)
async def check_server_list_prefix(ctx):
    await ctx.reply("Fetching server list...", ephemeral=True)
    try:
        resp = await ptero_request("GET", "/servers")
        data = resp.get("data", [])
        if not data:
            await ctx.reply("No servers found.")
            return
        lines = []
        for s in data[:25]:
            a = s["attributes"]
            lines.append(f"{a['name']} ({a['identifier']}) Owner: {a['user']}")
        if len(data) > 25:
            lines.append(f"...and {len(data)-25} more.")
        await ctx.reply("\n".join(lines))
    except Exception as e:
        await ctx.reply(f"Error listing: {e}")

@bot.command(name="nodes")
@commands.check(admin_check)
async def nodes_prefix(ctx):
    await ctx.reply("Fetching nodes...", ephemeral=True)
    try:
        resp = await ptero_request("GET", "/nodes")
        nodes = resp.get("data", [])
        if not nodes:
            await ctx.reply("No nodes.")
            return
        lines = []
        for node in nodes:
            a = node["attributes"]
            name = a.get("name", "unknown")
            memory = a.get("memory", 0)
            disk = a.get("disk", 0)
            status = "🟢 Online" if a.get("public", True) else "🔴 Offline"
            lines.append(f"{name}: {memory}MB RAM • {disk}MB Disk • {status}")
        await ctx.reply("\n".join(lines[:15]))
    except Exception as e:
        await ctx.reply(f"Error fetching nodes: {e}")

# SLASH COMMANDS

@tree.command(name="addadmin_bot", description="Add a discord user as admin for the bot.")
@app_commands.describe(userid="Discord user ID to add as admin")
async def addadmin_bot(interaction: Interaction, userid: str):
    if not is_admin_interaction(interaction.user):
        await interaction.response.send_message("Unauthorized.", ephemeral=True)
        return
    added = add_admin_raw(int(userid))
    if added:
        await interaction.response.send_message(f"Added {userid} to admin list.", ephemeral=True)
    else:
        await interaction.response.send_message(f"{userid} is already admin.", ephemeral=True)

@tree.command(name="create_acc", description="Create Pterodactyl account and DM credentials (admin only).")
@app_commands.describe(userid="Discord user ID to DM", email="Email for new account", password="Password to set")
async def create_acc(interaction: Interaction, userid: str, email: str, password: str):
    if not is_admin_interaction(interaction.user):
        await interaction.response.send_message("Unauthorized.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        payload = {
            "email": email,
            "username": f"user{userid}",
            "first_name": "User",
            "last_name": userid,
            "password": password,
            "language": "en"
        }
        resp = await ptero_request("POST", "/users", json_body=payload)
        # DM the target
        try:
            guild = interaction.guild
            member = await guild.fetch_member(int(userid))
            dm = await member.create_dm()
            await dm.send(f"Your panel account is created.\nEmail: {email}\nPassword: {password}\nPanel: {PTERO_BASE}")
            await interaction.followup.send(f"Account created and credentials sent to <@{userid}>.", ephemeral=True)
        except Exception:
            await interaction.followup.send(f"Account created. Credentials:\nEmail: {email}\nPassword: {password}\nPanel: {PTERO_BASE}", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Failed to create account: {e}", ephemeral=True)

@tree.command(name="create_server", description="Create a Paper Minecraft server with limits (admin only).")
@app_commands.describe(
    server_name="Name of the server",
    owner_email="Owner's panel email (must exist)",
    cpu_limit="CPU limit (integer)",
    memory_mb="Memory in MB",
    disk_mb="Disk in MB"
)
async def create_server(interaction: Interaction, server_name: str, owner_email: str, cpu_limit: int, memory_mb: int, disk_mb: int):
    if not is_admin_interaction(interaction.user):
        await interaction.response.send_message("Unauthorized.", ephemeral=True)
        return
    await interaction.response.defer()
    try:
        users_resp = await ptero_request("GET", f"/users?filter[email]={owner_email}")
        if not users_resp.get("data"):
            await interaction.followup.send_message(f"No user with email {owner_email}.", ephemeral=True)
            return
        user_id = users_resp["data"][0]["attributes"]["id"]
        server_payload = {
            "name": server_name,
            "user": user_id,
            # TODO: replace with actual nest/egg IDs corresponding to Paper
            "nest": 1,  # placeholder
            "egg": 7,   # placeholder for Paper egg
            "docker_image": "ghcr.io/pterodactyl/yolks:java_17",
            "startup": "java -Xms128M -Xmx{{SERVER_MEMORY}}M -jar paper.jar",
            "limits": {
                "memory": memory_mb,
                "swap": 0,
                "disk": disk_mb,
                "io": 500,
                "cpu": cpu_limit
            },
            "feature_limits": {
                "databases": 1,
                "allocations": 1
            },
            "environment": {
                "PAPER_VERSION": "latest"
            }
        }
        created = await ptero_request("POST", "/servers", json_body=server_payload)
        identifier = created["attributes"]["identifier"]
        await interaction.followup.send(f"Server '{server_name}' created with ID `{identifier}`.")
    except Exception as e:
        await interaction.followup.send(f"Error creating server: {e}")

@tree.command(name="remove_server", description="Delete a server by identifier (admin only).")
@app_commands.describe(serverid="Server identifier to delete")
async def remove_server(interaction: Interaction, serverid: str):
    if not is_admin_interaction(interaction.user):
        await interaction.response.send_message("Unauthorized.", ephemeral=True)
        return
    await interaction.response.defer()
    try:
        await ptero_request("DELETE", f"/servers/{serverid}")
        await interaction.followup.send(f"Server {serverid} deleted.")
    except Exception as e:
        await interaction.followup.send(f"Failed to delete: {e}")

@tree.command(name="check_server_list", description="List all servers (admin only).")
async def check_server_list(interaction: Interaction):
    if not is_admin_interaction(interaction.user):
        await interaction.response.send_message("Unauthorized.", ephemeral=True)
        return
    await interaction.response.defer()
    try:
        resp = await ptero_request("GET", "/servers")
        data = resp.get("data", [])
        if not data:
            await interaction.followup.send("No servers found.")
            return
        lines = []
        for s in data[:30]:
            a = s["attributes"]
            lines.append(f"{a['name']} ({a['identifier']}) Owner: {a['user']}")
        if len(data) > 30:
            lines.append(f"...and {len(data)-30} more.")
        await interaction.followup.send("\n".join(lines))
    except Exception as e:
        await interaction.followup.send(f"Failed: {e}")

# Manage view with controls
class ManageView(ui.View):
    def __init__(self, server_id: str):
        super().__init__(timeout=180)
        self.server_id = server_id

    async def _send_power_signal(self, interaction: Interaction, signal: str, label: str):
        await interaction.response.defer()
        try:
            await ptero_request("POST", f"/servers/{self.server_id}/power", json_body={"signal": signal})
            await interaction.followup.send(f"{label} signal sent.")
        except Exception as e:
            await interaction.followup.send(f"Failed to {label.lower()}: {e}")

    @ui.button(label="Start", style=discord.ButtonStyle.green, custom_id="manage_start")
    async def start(self, interaction: Interaction, button: ui.Button):
        await self._send_power_signal(interaction, "start", "Start")

    @ui.button(label="Stop", style=discord.ButtonStyle.red, custom_id="manage_stop")
    async def stop(self, interaction: Interaction, button: ui.Button):
        await self._send_power_signal(interaction, "stop", "Stop")

    @ui.button(label="Restart", style=discord.ButtonStyle.blurple, custom_id="manage_restart")
    async def restart(self, interaction: Interaction, button: ui.Button):
        await self._send_power_signal(interaction, "restart", "Restart")

    @ui.button(label="Reinstall", style=discord.ButtonStyle.gray, custom_id="manage_reinstall")
    async def reinstall(self, interaction: Interaction, button: ui.Button):
        await interaction.response.defer()
        try:
            await ptero_request("POST", f"/servers/{self.server_id}/reinstall")
            await interaction.followup.send("Reinstall triggered.")
        except Exception as e:
            await interaction.followup.send(f"Failed to reinstall: {e}")

    @ui.button(label="IP Info", style=discord.ButtonStyle.secondary, custom_id="manage_ipinfo")
    async def ipinfo(self, interaction: Interaction, button: ui.Button):
        await interaction.response.defer()
        try:
            server = await ptero_request("GET", f"/servers/{self.server_id}")
            allocs = server["attributes"]["relationships"]["allocations"]["data"]
            if not allocs:
                await interaction.followup.send("No allocation found.")
                return
            first = allocs[0]["attributes"]
            ip = first.get("ip", "unknown")
            port = first.get("port", "unknown")
            await interaction.followup.send(f"IP: {ip}:{port}")
        except Exception as e:
            await interaction.followup.send(f"Failed to fetch IP info: {e}")

@tree.command(name="manage", description="Manage a given server (admin only).")
@app_commands.describe(serverid="Server identifier to manage")
async def manage(interaction: Interaction, serverid: str):
    if not is_admin_interaction(interaction.user):
        await interaction.response.send_message("Unauthorized.", ephemeral=True)
        return
    await interaction.response.defer()
    try:
        server = await ptero_request("GET", f"/servers/{serverid}")
        attr = server["attributes"]
        status = attr.get("status", "unknown")
        resources = format_resources(attr)
        online = "🟢 Online" if status == "running" else "🔴 Offline"
        embed = discord.Embed(title=f"Manage Server: {attr.get('name','unknown')}",
                              color=0x00FF00 if status == "running" else 0xFF0000)
        embed.add_field(name="Status", value=online, inline=False)
        embed.add_field(name="Resources", value=resources, inline=False)
        owner = attr.get("user", "unknown")
        embed.add_field(name="Owner ID", value=str(owner), inline=True)
        view = ManageView(serverid)
        await interaction.followup.send(embed=embed, view=view)
    except Exception as e:
        await interaction.followup.send(f"Failed to fetch server: {e}")

@tree.command(name="nodes", description="Show Pterodactyl node statuses (admin only).")
async def nodes(interaction: Interaction):
    if not is_admin_interaction(interaction.user):
        await interaction.response.send_message("Unauthorized.", ephemeral=True)
        return
    await interaction.response.defer()
    try:
        resp = await ptero_request("GET", "/nodes")
        data = resp.get("data", [])
        if not data:
            await interaction.followup.send("No nodes.")
            return
        lines = []
        for node in data:
            a = node["attributes"]
            name = a.get("name", "unknown")
            memory = a.get("memory", 0)
            disk = a.get("disk", 0)
            status = "🟢 Online" if a.get("public", True) else "🔴 Offline"
            lines.append(f"{name}: {memory}MB RAM • {disk}MB Disk • {status}")
        await interaction.followup.send("\n".join(lines[:25]))
    except Exception as e:
        await interaction.followup.send(f"Failed to fetch nodes: {e}")

# Global error handlers
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.reply("Unauthorized or missing admin permission.")
    else:
        await ctx.reply(f"Error: {error}")

bot.run(DISCORD_TOKEN)
