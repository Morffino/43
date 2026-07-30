import discord
from discord import app_commands
from discord.ext import commands
import os
import sys
import re
import asyncio
from dotenv import load_dotenv
from aiohttp import web

load_dotenv()

# ---------- Конфигурация ----------
TOKEN = os.getenv('DISCORD_TOKEN')
MOD_CHANNEL_ID = int(os.getenv('MOD_CHANNEL_ID', 0))
LOG_CHANNEL_ID = int(os.getenv('LOG_CHANNEL_ID', 0))
ADMIN_ROLE_ID = int(os.getenv('ADMIN_ROLE_ID', 0))

if not TOKEN or MOD_CHANNEL_ID == 0:
    print("❌ Ошибка: не заданы DISCORD_TOKEN и MOD_CHANNEL_ID")
    sys.exit(1)

# ---------- Загрузка запрещённых доменов ----------
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
        # Создаём файл с примерами
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

# Регулярное выражение для поиска ссылок (простое)
URL_PATTERN = re.compile(r'(https?://\S+|www\.\S+)')

# ---------- Вспомогательные функции ----------
async def log_action(message: discord.Message, reason: str):
    """Отправляет лог в указанный канал."""
    if LOG_CHANNEL_ID == 0:
        return
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if not channel:
        return
    embed = discord.Embed(
        title="🚫 Автомодерация",
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

def contains_banned_domain(text: str) -> bool:
    """Проверяет, содержит ли текст ссылку на запрещённый домен."""
    urls = URL_PATTERN.findall(text.lower())
    for url in urls:
        # Извлекаем домен из URL
        for domain in banned_domains:
            if domain in url:  # простое совпадение подстроки (можно улучшить)
                return True
    return False

def is_invite_link(text: str) -> bool:
    """Проверка на пригласительные ссылки Discord."""
    invite_pattern = re.compile(r'(?:discord\.(?:gg|com/invite)/\S+)', re.IGNORECASE)
    return bool(invite_pattern.search(text))

def is_spam(text: str) -> bool:
    """Проверка на спам: более 3 ссылок в сообщении."""
    urls = URL_PATTERN.findall(text)
    return len(urls) > 3

# ---------- Событие on_message ----------
@bot.event
async def on_message(message: discord.Message):
    # Игнорируем сообщения от ботов
    if message.author.bot:
        return

    # Проверяем, что сообщение в модерируемом канале
    if message.channel.id != MOD_CHANNEL_ID:
        await bot.process_commands(message)
        return

    # Если у пользователя есть роль администратора, пропускаем (опционально)
    if ADMIN_ROLE_ID != 0:
        role = message.guild.get_role(ADMIN_ROLE_ID)
        if role and role in message.author.roles:
            await bot.process_commands(message)
            return

    content = message.content
    reason = None

    # Проверка на запрещённые домены
    if contains_banned_domain(content):
        reason = "Запрещённый домен"
    # Проверка на приглашения Discord
    elif is_invite_link(content):
        reason = "Пригласительная ссылка Discord"
    # Проверка на спам (много ссылок)
    elif is_spam(content):
        reason = "Спам (много ссылок)"

    # Если нарушение найдено
    if reason:
        try:
            await message.delete()
            await log_action(message, reason)
            # Уведомление пользователя в ЛС (опционально)
            try:
                embed = discord.Embed(
                    title="⚠️ Ваше сообщение удалено",
                    description=f"В канале {message.channel.mention} было удалено сообщение по причине: **{reason}**.",
                    color=discord.Color.orange()
                )
                await message.author.send(embed=embed)
            except:
                pass
            return
        except Exception as e:
            print(f"Ошибка удаления: {e}")

    # Передаём управление командам
    await bot.process_commands(message)

# ---------- Команда для добавления домена (только админы) ----------
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

# ---------- Команда для удаления домена ----------
@bot.tree.command(name="remove_domain", description="Удалить домен из чёрного списка (только админ)")
@app_commands.default_permissions(administrator=True)
async def remove_domain(interaction: discord.Interaction, domain: str):
    domain = domain.lower().strip()
    if domain not in banned_domains:
        await interaction.response.send_message(f"⚠️ Домен {domain} не найден в списке.", ephemeral=True)
        return
    banned_domains.remove(domain)
    # Перезаписываем файл
    with open(DOMAINS_FILE, "w", encoding="utf-8") as f:
        for d in sorted(banned_domains):
            f.write(d + "\n")
    await interaction.response.send_message(f"✅ Домен {domain} удалён из чёрного списка.", ephemeral=True)

# ---------- Команда для просмотра списка доменов ----------
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

# ---------- Команда для включения/отключения модерации (переключение канала) ----------
@bot.tree.command(name="set_mod_channel", description="Установить канал для автомодерации (только админ)")
@app_commands.default_permissions(administrator=True)
async def set_mod_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    global MOD_CHANNEL_ID
    MOD_CHANNEL_ID = channel.id
    await interaction.response.send_message(f"✅ Канал для автомодерации установлен: {channel.mention}", ephemeral=True)

# ---------- Веб-сервер для health check (для хостинга) ----------
async def health_check(request):
    return web.Response(text="OK", status=200)

async def start_web():
    app = web.Application()
    app.router.add_get('/health', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host='0.0.0.0', port=8080)
    await site.start()
    print("🌐 Health check на порту 8080")
    await asyncio.Event().wait()

# ---------- Событие готовности ----------
@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user} запущен!')
    print(f"📌 Модерация активна в канале ID: {MOD_CHANNEL_ID}")
    print(f"📋 Загружено доменов: {len(banned_domains)}")
    try:
        synced = await bot.tree.sync()
        print(f"🔄 Синхронизировано {len(synced)} команд.")
    except Exception as e:
        print(f"⚠️ Ошибка синхронизации: {e}")

# ---------- Запуск ----------
async def main():
    asyncio.create_task(start_web())
    await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
