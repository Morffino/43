import discord
from discord import app_commands
from discord.ext import commands
import os
import sys
import re
import asyncio
from datetime import timedelta
from dotenv import load_dotenv
from aiohttp import web

load_dotenv()

# ---------- Конфигурация ----------
TOKEN = os.getenv('DISCORD_TOKEN')
ADMIN_ROLE_ID = int(os.getenv('ADMIN_ROLE_ID', 0))

# Каналы для модерации
MOD_CHANNEL_IDS = [1529234469842587678, 1532365777712447568]
LOG_CHANNEL_ID = 1530954702320308326

if not TOKEN:
    print("❌ Ошибка: не задан DISCORD_TOKEN")
    sys.exit(1)

# ---------- Загрузка запрещённых доменов (оставляем для совместимости) ----------
DOMAINS_FILE = "banned_domains.txt"
banned_domains = set()

def load_domains():
    global banned_domains
    banned_domains = set()
    if os.path.exists(DOMAINS_FILE):
        with open(DOMAINS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                domain = line.strip().lower()
                if domain:
                    banned_domains.add(domain)
    else:
        with open(DOMAINS_FILE, "w", encoding="utf-8") as f:
            f.write("# Список запрещённых доменов (по одному на строку)\n")
            f.write("bit.ly\n")
            f.write("goo.gl\n")
            f.write("tinyurl.com\n")
            f.write("discord.gg\n")
            f.write("vk.com\n")
        print("⚠️ Файл banned_domains.txt создан с примерами. Добавьте свои домены.")

load_domains()

# ---------- Бот ----------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Регулярка для поиска любых ссылок
URL_PATTERN = re.compile(r'(https?://[^\s]+|www\.[^\s]+)', re.IGNORECASE)

# ---------- Вспомогательные функции ----------
async def log_action(message: discord.Message, reason: str, action: str = "Удалено"):
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if not channel:
        return
    embed = discord.Embed(
        title=f"🚫 {action}",
        color=discord.Color.red(),
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="Канал", value=message.channel.mention, inline=False)
    embed.add_field(name="Автор", value=message.author.mention, inline=False)
    embed.add_field(name="Сообщение", value=message.content[:1000], inline=False)
    embed.add_field(name="Причина", value=reason, inline=False)
    try:
        await channel.send(embed=embed)
    except:
        pass

def contains_any_link(text: str) -> bool:
    """Проверяет, есть ли в тексте любая ссылка."""
    return bool(URL_PATTERN.search(text))

def contains_banned_domain(text: str) -> bool:
    """Оставляем для совместимости (можно удалить, если не нужно)."""
    urls = URL_PATTERN.findall(text.lower())
    for url in urls:
        for domain in banned_domains:
            if domain in url:
                return True
    return False

def is_invite_link(text: str) -> bool:
    invite_pattern = re.compile(r'(?:discord\.(?:gg|com/invite)/\S+)', re.IGNORECASE)
    return bool(invite_pattern.search(text))

def is_spam(text: str) -> bool:
    urls = URL_PATTERN.findall(text)
    return len(urls) > 3

# ---------- Событие on_message ----------
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Проверяем, что сообщение в одном из модерируемых каналов
    if message.channel.id not in MOD_CHANNEL_IDS:
        await bot.process_commands(message)
        return

    # Если у пользователя есть роль администратора, пропускаем
    if ADMIN_ROLE_ID != 0:
        role = message.guild.get_role(ADMIN_ROLE_ID)
        if role and role in message.author.roles:
            await bot.process_commands(message)
            return

    content = message.content
    reason = None

    # ---- НОВАЯ ПРОВЕРКА: любая ссылка ----
    if contains_any_link(content):
        reason = "Публикация ссылки (запрещено)"
    # ---- Остальные проверки (можно оставить, но они уже не нужны) ----
    elif contains_banned_domain(content):
        reason = "Запрещённый домен"
    elif is_invite_link(content):
        reason = "Пригласительная ссылка Discord"
    elif is_spam(content):
        reason = "Спам (много ссылок)"

    if reason:
        try:
            await message.delete()
            await log_action(message, reason, action="Мут + удаление")

            member = message.author
            if member.guild_permissions.administrator:
                await message.channel.send(f"⚠️ Не могу замутить администратора {member.mention}", delete_after=5)
            else:
                try:
                    await member.timeout(timedelta(hours=15), reason=f"Автоматический мут за {reason}")
                    try:
                        embed = discord.Embed(
                            title="⏰ Вы получили мут",
                            description=f"Вы были замучены на 15 часов за публикацию запрещённого контента.\nПричина: **{reason}**.",
                            color=discord.Color.orange()
                        )
                        await member.send(embed=embed)
                    except:
                        pass
                except Exception as e:
                    print(f"Ошибка при выдаче мута: {e}")
            return
        except Exception as e:
            print(f"Ошибка обработки нарушения: {e}")

    await bot.process_commands(message)

# ---------- Команды для управления доменами (оставляем) ----------
@bot.tree.command(name="add_domain", description="Добавить домен в чёрный список (только админ)")
@app_commands.default_permissions(administrator=True)
async def add_domain(interaction: discord.Interaction, domain: str):
    domain = domain.lower().strip()
    if not domain:
        await interaction.response.send_message("❌ Укажите домен.", ephemeral=True)
        return
    if domain in banned_domains:
        await interaction.response.send_message(f"⚠️ Домен {domain} уже в списке.", ephemeral=True)
        return
    banned_domains.add(domain)
    with open(DOMAINS_FILE, "a", encoding="utf-8") as f:
        f.write(domain + "\n")
    await interaction.response.send_message(f"✅ Домен {domain} добавлен в чёрный список.", ephemeral=True)

@bot.tree.command(name="remove_domain", description="Удалить домен из чёрного списка (только админ)")
@app_commands.default_permissions(administrator=True)
async def remove_domain(interaction: discord.Interaction, domain: str):
    domain = domain.lower().strip()
    if domain not in banned_domains:
        await interaction.response.send_message(f"⚠️ Домен {domain} не найден в списке.", ephemeral=True)
        return
    banned_domains.remove(domain)
    with open(DOMAINS_FILE, "w", encoding="utf-8") as f:
        for d in sorted(banned_domains):
            f.write(d + "\n")
    await interaction.response.send_message(f"✅ Домен {domain} удалён из чёрного списка.", ephemeral=True)

@bot.tree.command(name="list_domains", description="Показать список запрещённых доменов")
@app_commands.default_permissions(administrator=True)
async def list_domains(interaction: discord.Interaction):
    if not banned_domains:
        await interaction.response.send_message("📭 Список пуст.", ephemeral=True)
        return
    domains_text = "\n".join(sorted(banned_domains))
    if len(domains_text) > 1900:
        domains_text = domains_text[:1900] + "..."
    await interaction.response.send_message(f"📋 **Запрещённые домены:**\n{domains_text}", ephemeral=True)

# ---------- Веб-сервер для health check (исправлен) ----------
PORT = int(os.getenv('PORT', 8080))

async def health_check(request):
    return web.Response(text="OK", status=200)

async def start_web():
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host='0.0.0.0', port=PORT)
    await site.start()
    print(f"🌐 Health check доступен по адресам: / и /health на порту {PORT}")
    await asyncio.Event().wait()

@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user} запущен!')
    print(f"📌 Модерация активна в каналах: {MOD_CHANNEL_IDS}")
    print(f"📋 Загружено доменов: {len(banned_domains)}")
    try:
        synced = await bot.tree.sync()
        print(f"🔄 Синхронизировано {len(synced)} команд.")
    except Exception as e:
        print(f"⚠️ Ошибка синхронизации: {e}")

async def main():
    asyncio.create_task(start_web())
    await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
