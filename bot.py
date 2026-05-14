import discord
from discord.ext import commands
from discord import app_commands
import psycopg2
import psycopg2.pool
import secrets
import string
import os

# ============================
BOT_TOKEN       = "YOUR_BOT_TOKEN"
ADMIN_IDS       = [1299861151248814102]
DOWNLOAD_URL    = "https://example.com/download"
PANEL_IMAGE_URL = ""
DATABASE_URL    = os.environ.get("DATABASE_URL", "")
# ============================

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

db_pool = None

def get_pool():
    global db_pool
    if db_pool is None:
        db_pool = psycopg2.pool.SimpleConnectionPool(1, 5, DATABASE_URL)
    return db_pool

def get_db():
    return get_pool().getconn()

def put_db(conn):
    get_pool().putconn(conn)

def init_db():
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS keys (
                key      TEXT PRIMARY KEY,
                used     INTEGER DEFAULT 0,
                used_by  TEXT DEFAULT NULL,
                hwid     TEXT DEFAULT NULL
            )
        """)
        conn.commit()
    finally:
        put_db(conn)

def generate_key():
    chars = string.ascii_uppercase + string.digits
    parts = ["".join(secrets.choice(chars) for _ in range(4)) for _ in range(3)]
    return "KEY-" + "-".join(parts)

def insert_keys(keys):
    conn = get_db()
    count = 0
    try:
        c = conn.cursor()
        for key in keys:
            try:
                c.execute("INSERT INTO keys (key) VALUES (%s) ON CONFLICT DO NOTHING", (key,))
                count += c.rowcount
            except Exception:
                pass
        conn.commit()
    finally:
        put_db(conn)
    return count

def check_and_use_key(key, user_id):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT used, used_by FROM keys WHERE key = %s", (key,))
        row = c.fetchone()
        if row is None:    return "invalid"
        if row[0]:         return "already_used"
        c.execute("UPDATE keys SET used = 1, used_by = %s WHERE key = %s", (user_id, key))
        conn.commit()
        return "valid"
    finally:
        put_db(conn)

def has_redeemed(user_id):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT 1 FROM keys WHERE used_by = %s AND used = 1", (user_id,))
        return c.fetchone() is not None
    finally:
        put_db(conn)


# ── /redeem ───────────────────────────────────────────────────────

@bot.tree.command(name="redeem", description="รีดีมคีย์ของคุณ")
@app_commands.describe(key="ใส่คีย์ที่ต้องการรีดีม")
async def redeem(interaction: discord.Interaction, key: str):
    result = check_and_use_key(key.strip().upper(), str(interaction.user.id))
    if result == "valid":
        embed = discord.Embed(
            title="✅ รีดีมสำเร็จ!",
            description=(
                f"คีย์ `{key}` ถูกต้องแล้ว\n\n"
                "นำคีย์นี้ไปใส่ในโปรแกรม Storm Launcher เพื่อเปิดใช้งาน 🚀\n"
                "**⚠️** คีย์ 1 ใบ = 1 เครื่องเท่านั้น"
            ),
            color=discord.Color.green()
        )
    elif result == "already_used":
        embed = discord.Embed(title="⚠️ คีย์ถูกใช้ไปแล้ว", color=discord.Color.orange())
    else:
        embed = discord.Embed(title="❌ คีย์ไม่ถูกต้อง", color=discord.Color.red())
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ── /genkey ───────────────────────────────────────────────────────

@bot.tree.command(name="genkey", description="[Admin] สร้างคีย์แบบสุ่ม")
@app_commands.describe(amount="จำนวนคีย์ (สูงสุด 25)")
async def genkey(interaction: discord.Interaction, amount: int = 1):
    if interaction.user.id not in ADMIN_IDS:
        await interaction.response.send_message("🚫 ไม่มีสิทธิ์", ephemeral=True); return
    amount = max(1, min(amount, 25))
    new_keys = [generate_key() for _ in range(amount)]
    inserted = insert_keys(new_keys)
    key_list = "\n".join(f"`{k}`" for k in new_keys)
    embed = discord.Embed(title=f"🔑 สร้างคีย์สำเร็จ {inserted} คีย์", description=key_list, color=discord.Color.blue())
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ── /resethwid ────────────────────────────────────────────────────

@bot.tree.command(name="resethwid", description="[Admin] Reset HWID ของคีย์")
@app_commands.describe(key="คีย์ที่ต้องการ Reset HWID")
async def resethwid(interaction: discord.Interaction, key: str):
    if interaction.user.id not in ADMIN_IDS:
        await interaction.response.send_message("🚫 ไม่มีสิทธิ์", ephemeral=True); return

    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT used, hwid FROM keys WHERE key = %s", (key.strip().upper(),))
        row = c.fetchone()

        if row is None:
            embed = discord.Embed(title="❌ ไม่พบคีย์นี้", color=discord.Color.red())
        elif not row[0]:
            embed = discord.Embed(title="⚠️ คีย์ยังไม่ได้ถูกใช้งาน", color=discord.Color.orange())
        else:
            old_hwid = row[1]
            c.execute("UPDATE keys SET hwid = NULL WHERE key = %s", (key.strip().upper(),))
            conn.commit()
            embed = discord.Embed(
                title="✅ Reset HWID สำเร็จ",
                description=f"คีย์ `{key}` พร้อมใช้งานบนเครื่องใหม่แล้ว\n**HWID เก่า:** `{old_hwid or 'ไม่มี'}`",
                color=discord.Color.green()
            )
    finally:
        put_db(conn)

    await interaction.response.send_message(embed=embed, ephemeral=True)


# ── /keyinfo ──────────────────────────────────────────────────────

@bot.tree.command(name="keyinfo", description="[Admin] ดูข้อมูลคีย์ทั้งหมด")
async def keyinfo(interaction: discord.Interaction):
    if interaction.user.id not in ADMIN_IDS:
        await interaction.response.send_message("🚫 ไม่มีสิทธิ์", ephemeral=True); return

    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM keys"); total = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM keys WHERE used = 1"); used_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM keys WHERE used = 1 AND hwid IS NOT NULL"); hwid_bound = c.fetchone()[0]
        c.execute("SELECT key, used_by, hwid FROM keys WHERE used = 1"); used_rows = c.fetchall()
        c.execute("SELECT key FROM keys WHERE used = 0"); unused_rows = c.fetchall()
    finally:
        put_db(conn)

    embed = discord.Embed(title="📊 สรุปข้อมูลคีย์", color=discord.Color.blue())
    embed.add_field(name="🔑 ทั้งหมด",        value=str(total),               inline=True)
    embed.add_field(name="✅ ใช้แล้ว",         value=str(used_count),          inline=True)
    embed.add_field(name="🟡 ยังไม่ใช้",       value=str(total - used_count),  inline=True)
    embed.add_field(name="💻 ผูก HWID แล้ว",  value=str(hwid_bound),          inline=True)
    embed.add_field(name="⏳ รอใส่โปรแกรม",   value=str(used_count - hwid_bound), inline=True)

    if used_rows:
        lst = "\n".join(f"`{k}` → <@{uid}> {'🖥️' if hw else '⏳'}" for k, uid, hw in used_rows)
        if len(lst) > 1020: lst = lst[:1020] + "..."
        embed.add_field(name="✅ ใช้แล้ว", value=lst, inline=False)

    if unused_rows:
        lst = "\n".join(f"`{r[0]}`" for r in unused_rows)
        if len(lst) > 1020: lst = lst[:1020] + "..."
        embed.add_field(name="🟡 ยังไม่ใช้", value=lst, inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)


# ── Panel ─────────────────────────────────────────────────────────

class RedeemModal(discord.ui.Modal, title="🔑 Redeem Key"):
    key_input = discord.ui.TextInput(label="API Key", placeholder="KEY-XXXX-XXXX-XXXX", min_length=3, max_length=64)

    async def on_submit(self, interaction: discord.Interaction):
        key = self.key_input.value.strip().upper()
        result = check_and_use_key(key, str(interaction.user.id))
        if result == "valid":
            embed = discord.Embed(
                title="✅ Redeem สำเร็จ!",
                description=f"คีย์ `{key}` ถูกต้อง\nนำไปใส่ใน Storm Launcher ได้เลย ⬇️\n**⚠️** คีย์ 1 ใบ = 1 เครื่อง",
                color=discord.Color.green()
            )
        elif result == "already_used":
            embed = discord.Embed(title="⚠️ คีย์ถูกใช้ไปแล้ว", color=discord.Color.orange())
        else:
            embed = discord.Embed(title="❌ คีย์ผิด", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)


class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Redeem Key", style=discord.ButtonStyle.success, emoji="🔑", custom_id="panel:redeem")
    async def redeem_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RedeemModal())

    @discord.ui.button(label="Download", style=discord.ButtonStyle.primary, emoji="⬇️", custom_id="panel:download")
    async def download_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_redeemed(str(interaction.user.id)):
            embed = discord.Embed(title="🔒 กรุณารีดีมคีย์ก่อน", color=discord.Color.red())
        else:
            embed = discord.Embed(title="✅ ดาวน์โหลดได้เลย!", description=f"[คลิกที่นี่]({DOWNLOAD_URL})", color=discord.Color.green())
        await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="panel", description="[Admin] โพสต์ Panel")
async def panel(interaction: discord.Interaction, title: str = "Storm Launcher", description: str = "Redeem your key or download below."):
    if interaction.user.id not in ADMIN_IDS:
        await interaction.response.send_message("🚫 ไม่มีสิทธิ์", ephemeral=True); return
    embed = discord.Embed(title=title, description=description, color=0x1e90ff)
    if PANEL_IMAGE_URL:
        embed.set_image(url=PANEL_IMAGE_URL)
    await interaction.response.send_message(embed=embed, view=PanelView())


# ── on_ready ──────────────────────────────────────────────────────

@bot.event
async def on_ready():
    init_db()
    bot.add_view(PanelView())
    synced = await bot.tree.sync()
    print(f"✅ {bot.user} | Synced {len(synced)} commands")

bot.run(BOT_TOKEN)
