import discord
from discord import app_commands
import aiohttp
import os
from dotenv import load_dotenv
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

class PterodactylBot:
    def __init__(self):
        self.ptero_url = os.getenv('PTERODACTYL_URL')
        self.api_key = os.getenv('PTERODACTYL_API_KEY')
        self.admin_role_id = int(os.getenv('ADMIN_ROLE_ID'))

    async def check_admin(self, interaction: discord.Interaction) -> bool:
        if any(role.id == self.admin_role_id for role in interaction.user.roles):
            return True
        await interaction.response.send_message("Only admins can use this command!", ephemeral=True)
        return False

    async def get_headers(self):
        return {
            'Authorization': f'Bearer {self.api_key}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }

ptero = PterodactylBot()

@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user}')
    try:
        synced = await tree.sync()
        logger.info(f'Synced {len(synced)} command(s)')
    except Exception as e:
        logger.error(f'Failed to sync commands: {str(e)}')

@tree.command(name="createserver", description="Create a new server in Pterodactyl")
@app_commands.describe(
    servername="Name of the server",
    owneremail="Email of the server owner",
    cpu="CPU limit in percentage (e.g., 200 for 2 cores)",
    memory="Memory limit in MB (e.g., 4096 for 4GB)",
    disk="Disk space in MB (e.g., 10240 for 10GB)",
    nest="Nest to select (e.g., Minecraft)",
    egg="Egg to select (e.g., Paper)"
)
async def createserver(interaction: discord.Interaction, servername: str, owneremail: str, cpu: int, memory: int, disk: int, nest: str, egg: str):
    if not await ptero.check_admin(interaction):
        return

    await interaction.response.defer(ephemeral=True)
    async with aiohttp.ClientSession() as session:
        try:
            # Find user by email
            async with session.get(f'{ptero.ptero_url}/api/application/users?filter[email]={owneremail}', headers=await ptero.get_headers()) as resp:
                if resp.status != 200 or not (data := await resp.json())['data']:
                    return await interaction.followup.send(f"No user found with email {owneremail}.", ephemeral=True)
                user_id = data['data'][0]['attributes']['id']

            # Find nest
            async with session.get(f'{ptero.ptero_url}/api/application/nests', headers=await ptero.get_headers()) as resp:
                if resp.status != 200:
                    return await interaction.followup.send("Failed to fetch nests.", ephemeral=True)
                nests = (await resp.json())['data']
                nest_data = next((n for n in nests if n['attributes']['name'].lower() == nest.lower()), None)
                if not nest_data:
                    return await interaction.followup.send(f"Nest {nest} not found.", ephemeral=True)
                nest_id = nest_data['attributes']['id']

            # Find egg
            async with session.get(f'{ptero.ptero_url}/api/application/nests/{nest_id}/eggs', headers=await ptero.get_headers()) as resp:
                if resp.status != 200:
                    return await interaction.followup.send("Failed to fetch eggs.", ephemeral=True)
                eggs = (await resp.json())['data']
                egg_data = next((e for e in eggs if e['attributes']['name'].lower().startswith(egg.lower())), None)
                if not egg_data:
                    return await interaction.followup.send(f"Egg {egg} not found in nest {nest}.", ephemeral=True)
                egg_id = egg_data['attributes']['id']

            # Find allocation
            async with session.get(f'{ptero.ptero_url}/api/application/nodes/1/allocations', headers=await ptero.get_headers()) as resp:
                if resp.status != 200:
                    return await interaction.followup.send("Failed to fetch allocations.", ephemeral=True)
                allocations = (await resp.json())['data']
                allocation = next((a for a in allocations if not a['attributes']['assigned']), None)
                if not allocation:
                    return await interaction.followup.send("No available allocations.", ephemeral=True)
                allocation_id = allocation['attributes']['id']

            # Create server
            payload = {
                "name": servername,
                "user": user_id,
                "egg": egg_id,
                "docker_image": "quay.io/pterodactyl/core:java" if nest.lower() == "minecraft" else "quay.io/pterodactyl/core:generic",
                "startup": "java -Xms128M -Xmx{{SERVER_MEMORY}}M -jar server.jar" if nest.lower() == "minecraft" else "{{STARTUP}}",
                "environment": {"SERVER_JARFILE": "server.jar", "MINECRAFT_VERSION": "1.21.1"} if nest.lower() == "minecraft" else {},
                "limits": {"memory": memory, "swap": 0, "disk": disk, "io": 500, "cpu": cpu},
                "feature_limits": {"databases": 0, "backups": 1},
                "allocation": {"default": allocation_id}
            }
            async with session.post(f'{ptero.ptero_url}/api/application/servers', json=payload, headers=await ptero.get_headers()) as resp:
                if resp.status == 201:
                    await interaction.followup.send(f"Server '{servername}' created for {owneremail}!", ephemeral=True)
                else:
                    await interaction.followup.send(f"Failed to create server: {(await resp.json()).get('errors', 'Unknown error')}", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in createserver: {str(e)}")
            await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)

@tree.command(name="removeserver", description="Delete a server by ID")
@app_commands.describe(serverid="Server ID to delete")
async def removeserver(interaction: discord.Interaction, serverid: int):
    if not await ptero.check_admin(interaction):
        return

    await interaction.response.defer(ephemeral=True)
    async with aiohttp.ClientSession() as session:
        try:
            async with session.delete(f'{ptero.ptero_url}/api/application/servers/{serverid}', headers=await ptero.get_headers()) as resp:
                if resp.status == 204:
                    await interaction.followup.send(f"Server ID {serverid} deleted successfully!", ephemeral=True)
                else:
                    await interaction.followup.send(f"Failed to delete server: {(await resp.json()).get('errors', 'Unknown error')}", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in removeserver: {str(e)}")
            await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)

@tree.command(name="checkserverlist", description="List all servers")
async def checkserverlist(interaction: discord.Interaction):
    if not await ptero.check_admin(interaction):
        return

    await interaction.response.defer(ephemeral=True)
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f'{ptero.ptero_url}/api/application/servers', headers=await ptero.get_headers()) as resp:
                if resp.status != 200:
                    return await interaction.followup.send("Failed to fetch server list.", ephemeral=True)
                servers = (await resp.json())['data']
                embed = discord.Embed(title="Server List", color=discord.Color.blue())
                for server in servers[:25]:  # Limit to 25 to avoid embed size issues
                    attrs = server['attributes']
                    embed.add_field(
                        name=attrs['name'],
                        value=f"ID: {attrs['id']}\nOwner: {attrs['user']}\nStatus: {'Running' if not attrs['is_suspended'] else 'Suspended'}",
                        inline=False
                    )
                await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Error in checkserverlist: {str(e)}")
            await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)

@tree.command(name="createacc", description="Create a Pterodactyl user account")
@app_commands.describe(userid="Discord User ID", email="User email", password="User password")
async def createacc(interaction: discord.Interaction, userid: str, email: str, password: str):
    if not await ptero.check_admin(interaction):
        return

    await interaction.response.defer(ephemeral=True)
    async with aiohttp.ClientSession() as session:
        try:
            payload = {
                "username": f"user_{userid}",
                "email": email,
                "first_name": "User",
                "last_name": userid,
                "password": password
            }
            async with session.post(f'{ptero.ptero_url}/api/application/users', json=payload, headers=await ptero.get_headers()) as resp:
                if resp.status == 201:
                    user = await bot.fetch_user(int(userid))
                    dm_embed = discord.Embed(
                        title="Your Pterodactyl Account",
                        description=f"**Email**: {email}\n**Password**: {password}\n**Panel**: {ptero.ptero_url}",
                        color=discord.Color.green()
                    )
                    try:
                        await user.send(embed=dm_embed)
                        await interaction.followup.send(f"Account created for {email}. Credentials sent to user ID {userid}.", ephemeral=True)
                    except discord.Forbidden:
                        await interaction.followup.send(f"Account created, but could not DM user ID {userid}.", ephemeral=True)
                else:
                    await interaction.followup.send(f"Failed to create account: {(await resp.json()).get('errors', 'Unknown error')}", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in createacc: {str(e)}")
            await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)

@tree.command(name="manage", description="Manage a server with buttons")
@app_commands.describe(accountapikey="Pterodactyl client API key", email="Email to set permissions")
async def manage(interaction: discord.Interaction, accountapikey: str, email: str):
    if not await ptero.check_admin(interaction):
        return

    await interaction.response.defer()
    async with aiohttp.ClientSession() as session:
        try:
            # Get user ID by email
            async with session.get(f'{ptero.ptero_url}/api/application/users?filter[email]={email}', headers=await ptero.get_headers()) as resp:
                if resp.status != 200 or not (data := await resp.json())['data']:
                    return await interaction.followup.send(f"No user found with email {email}.", ephemeral=True)
                user_id = data['data'][0]['attributes']['id']

            # Get server list for user
            async with session.get(f'{ptero.ptero_url}/api/application/servers', headers=await ptero.get_headers()) as resp:
                if resp.status != 200:
                    return await interaction.followup.send("Failed to fetch servers.", ephemeral=True)
                servers = [s for s in (await resp.json())['data'] if s['attributes']['user'] == user_id]
                if not servers:
                    return await interaction.followup.send(f"No servers found for {email}.", ephemeral=True)
                server = servers[0]['attributes']  # Use first server for simplicity

            # Get server status and resources
            client_headers = {'Authorization': f'Bearer {accountapikey}', 'Accept': 'application/json'}
            async with session.get(f'{ptero.ptero_url}/api/client/servers/{server["identifier"]}/resources', headers=client_headers) as resp:
                if resp.status != 200:
                    return await interaction.followup.send("Failed to fetch server status.", ephemeral=True)
                resources = (await resp.json())['attributes']

            # Create embed
            status = "Online" if resources['current_state'] == 'running' else "Offline"
            embed = discord.Embed(
                title=f"Server: {server['name']}",
                description=(
                    f"**Status**: {status}\n"
                    f"**RAM**: {resources['resources']['memory_bytes'] / 1_000_000_000:.2f}GB/{server['limits']['memory'] / 1000}GB\n"
                    f"**CPU**: {resources['resources']['cpu_absolute']}%/{server['limits']['cpu']}%\n"
                    f"**Disk**: {resources['resources']['disk_bytes'] / 1_000_000_000:.2f}GB/{server['limits']['disk'] / 1000}GB\n"
                    f"**IP**: {server['allocation']['ip']}:{server['allocation']['port']}"
                ),
                color=discord.Color.green() if status == "Online" else discord.Color.red()
            )

            # Create buttons
            view = discord.ui.View()
            actions = [
                ("Start", "start", discord.ButtonStyle.green),
                ("Stop", "stop", discord.ButtonStyle.red),
                ("Restart", "restart", discord.ButtonStyle.blurple),
                ("Reinstall", "reinstall", discord.ButtonStyle.grey),
                ("Reload", "reload", discord.ButtonStyle.grey)
            ]
            for label, action, style in actions:
                async def button_callback(interaction: discord.Interaction, action=action):
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            f'{ptero.ptero_url}/api/client/servers/{server["identifier"]}/power',
                            json={"signal": action},
                            headers=client_headers
                        ) as resp:
                            if resp.status in (200, 204):
                                await interaction.response.send_message(f"{action.capitalize()} command sent!", ephemeral=True)
                            else:
                                await interaction.response.send_message(f"Failed to {action} server.", ephemeral=True)
                button = discord.ui.Button(label=label, style=style)
                button.callback = button_callback
                view.add_item(button)

            # File management buttons (placeholder)
            async def file_action(interaction: discord.Interaction, action):
                await interaction.response.send_message(f"{action} file feature not implemented in this example.", ephemeral=True)
            view.add_item(discord.ui.Button(label="Upload File", style=discord.ButtonStyle.grey, custom_id="upload_file", callback=lambda i: file_action(i, "Upload")))
            view.add_item(discord.ui.Button(label="Delete File", style=discord.ButtonStyle.grey, custom_id="delete_file", callback=lambda i: file_action(i, "Delete")))

            # Permissions button
            async def set_permissions(interaction: discord.Interaction):
                async with aiohttp.ClientSession() as session:
                    async with session.patch(
                        f'{ptero.ptero_url}/api/application/users/{user_id}',
                        json={"admin": True},
                        headers=await ptero.get_headers()
                    ) as resp:
                        if resp.status == 200:
                            await interaction.response.send_message(f"Admin permissions set for {email}.", ephemeral=True)
                        else:
                            await interaction.response.send_message(f"Failed to set permissions.", ephemeral=True)
            view.add_item(discord.ui.Button(label="Set Admin", style=discord.ButtonStyle.grey, custom_id="set_admin", callback=set_permissions))

            await interaction.followup.send(embed=embed, view=view)

@tree.command(name="nodes", description="Show Pterodactyl node status")
async def nodes(interaction: discord.Interaction):
    if not await ptero.check_admin(interaction):
        return

    await interaction.response.defer(ephemeral=True)
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f'{ptero.ptero_url}/api/application/nodes', headers=await ptero.get_headers()) as resp:
                if resp.status != 200:
                    return await interaction.followup.send("Failed to fetch nodes.", ephemeral=True)
                nodes = (await resp.json())['data']
                embed = discord.Embed(title="Node Status", color=discord.Color.blue())
                for node in nodes:
                    attrs = node['attributes']
                    status = "Online" if attrs['is_online'] else "Offline"
                    embed.add_field(
                        name=attrs['name'],
                        value=(
                            f"**Status**: {status}\n"
                            f"**RAM**: {attrs['memory_used'] / 1_000_000_000:.2f}GB/{attrs['memory'] / 1_000_000_000}GB\n"
                            f"**Disk**: {attrs['disk_used'] / 1_000_000_000:.2f}GB/{attrs['disk'] / 1_000_000_000}TB"
                        ),
                        inline=False
                    )
                view = discord.ui.View()
                view.add_item(discord.ui.Button(label="Panel", url=ptero.ptero_url, style=discord.ButtonStyle.link))
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        except Exception as e:
            logger.error(f"Error in nodes: {str(e)}")
            await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)

@tree.command(name="addadmin_bot", description="Add a user as bot admin")
@app_commands.describe(userid="Discord User ID to add as admin")
async def addadmin_bot(interaction: discord.Interaction, userid: str):
    if not await ptero.check_admin(interaction):
        return

    await interaction.response.defer(ephemeral=True)
    try:
        user = await bot.fetch_user(int(userid))
        role = interaction.guild.get_role(ptero.admin_role_id)
        await user.add_roles(role)
        await interaction.followup.send(f"User {user.name} added as bot admin!", ephemeral=True)
    except Exception as e:
        logger.error(f"Error in addadmin_bot: {str(e)}")
        await interaction.followup.send(f"Error: {str(e)}", ephemeral=True)

bot.run(os.getenv('DISCORD_TOKEN'))
