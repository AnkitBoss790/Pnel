import discord
from discord.ext import commands
import os
import paramiko
import random
import string
from datetime import datetime

TOKEN = 'YOUR_DISCORD_BOT_TOKEN'
PREFIX = '.'
SSH_HOST = 'YOUR_SSH_HOST'
SSH_USER = 'root'
SSH_KEY_PATH = '/path/to/private/key'

bot = commands.Bot(command_prefix=PREFIX, intents=discord.Intents.all())

def create_ssh_client():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(SSH_HOST, username=SSH_USER, key_filename=SSH_KEY_PATH)
    return ssh

async def deploy_vps(user_id):
    username = f'user{random.randint(1000, 9999)}'
    password = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    port = random.randint(20000, 30000)

    ssh = create_ssh_client()
    commands = [
        f'adduser --disabled-password --gecos "" {username}',
        f'echo "{username}:{password}" | chpasswd',
        f'ufw allow {port}',
        f'echo "Match User {username}\n  Port {port}" >> /etc/ssh/sshd_config',
        'systemctl restart ssh'
    ]
    for cmd in commands:
        stdin, stdout, stderr = ssh.exec_command(cmd)
        stdout.channel.recv_exit_status()
    ssh.close()

    return username, password, port

@bot.command()
async def deploy(ctx):
    username, password, port = await deploy_vps(ctx.author.id)
    embed = discord.Embed(title="VPS Deployed", description="Your VPS details have been generated.", color=discord.Color.green())
    embed.add_field(name="Username", value=username)
    embed.add_field(name="Password", value=password)
    embed.add_field(name="Port", value=port)
    embed.set_footer(text="Keep your details secure!")
    await ctx.author.send(embed=embed)
    await ctx.send("Your VPS details have been sent via DM.")

@bot.command()
async def check(ctx):
    if not ctx.message.attachments:
        await ctx.send("Please attach a screenshot for verification.")
        return

    attachment = ctx.message.attachments[0]
    file_path = f"./screenshots/{attachment.filename}"
    await attachment.save(file_path)
    await ctx.send(f"Screenshot {attachment.filename} saved for verification.")

@bot.event
async def on_ready():
    print(f"Bot is online as {bot.user}")

bot.run(TOKEN)
