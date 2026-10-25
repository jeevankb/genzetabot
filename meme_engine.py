# -*- coding: utf-8 -*-
"""
meme_engine.py
Dynamic Meme Image Generator & Asset Manager for GenZetaBot / GunYamazaki.
Generates and manages stylish, high-resolution anime & gaming meme graphic cards.
"""

import os
import random
from PIL import Image, ImageDraw, ImageFont

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMES_DIR = os.path.join(WORKSPACE_DIR, "memes")

# Ensure memes directory exists
os.makedirs(MEMES_DIR, exist_ok=True)

# Curated catalog of top iconic Anime & Gaming memes
MEME_CATALOG = [
    {
        "id": "gojo_nah_id_win",
        "title": "NAH, I'D WIN.",
        "character": "Gojo Satoru • Jujutsu Kaisen",
        "emoji": "🤞",
        "punchline": "Bro had 100% confidence before getting off-screened into two pieces 💀",
        "bg_color": (15, 23, 42),       # Dark Slate Navy
        "accent_color": (56, 189, 248),  # Electric Cyan
        "tag": "#JJK #GojoSatoru #NahIdWin"
    },
    {
        "id": "sung_jinwoo_arise",
        "title": "ARISE!",
        "character": "Sung Jinwoo • Solo Leveling",
        "emoji": "👑",
        "punchline": "When mom yells at you to wake up at 7 AM on a Sunday morning: 'Arise' 💀",
        "bg_color": (24, 15, 38),       # Dark Shadow Purple
        "accent_color": (168, 85, 247),  # Glowing Violet
        "tag": "#SoloLeveling #ShadowMonarch #Arise"
    },
    {
        "id": "cj_here_we_go_again",
        "title": "AH SHIT, HERE WE GO AGAIN",
        "character": "Carl Johnson (CJ) • GTA San Andreas",
        "emoji": "🚲",
        "punchline": "Walking into 8:30 AM Monday lecture with 62% attendance shortage...",
        "bg_color": (28, 25, 23),       # Deep Street Brown
        "accent_color": (245, 158, 11),  # Gold Amber
        "tag": "#GTASanAndreas #CollegeLife #MondayBlues"
    },
    {
        "id": "anya_smug_heh",
        "title": "HEH.",
        "character": "Anya Forger • Spy x Family",
        "emoji": "😏",
        "punchline": "When your friend swears 'Bhai kal pakka subah 6 baje gym chalenge' 😂",
        "bg_color": (38, 20, 30),       # Dark Rose
        "accent_color": (244, 63, 94),   # Rose Red
        "tag": "#SpyxFamily #Anya #GymFails"
    },
    {
        "id": "sukuna_stand_proud",
        "title": "STAND PROUD, YOU ARE STRONG",
        "character": "Ryomen Sukuna • Jujutsu Kaisen",
        "emoji": "🔥",
        "punchline": "Me consoling my bottom-frag Reyna teammate who finished match with 2 kills 💀",
        "bg_color": (40, 15, 15),       # Blood Crimson
        "accent_color": (239, 68, 68),   # Fiery Red
        "tag": "#Sukuna #Valorant #BottomFrag"
    },
    {
        "id": "zoro_lost_maps",
        "title": "ZORO LOST IN GOOGLE MAPS",
        "character": "Roronoa Zoro • One Piece",
        "emoji": "🧭",
        "punchline": "Told him to plant spike on B Site Haven, he somehow ended up in Dust 2 💀",
        "bg_color": (15, 35, 25),       # Forest Jade
        "accent_color": (34, 197, 94),   # Emerald Green
        "tag": "#OnePiece #Zoro #ValorantTrolls"
    },
    {
        "id": "this_is_fine_dog",
        "title": "THIS IS FINE.",
        "character": "Question Hound • KC Green",
        "emoji": "☕",
        "punchline": "Semester exam tomorrow, syllabus is 5 units, and haven't opened notes yet 😂",
        "bg_color": (35, 25, 15),       # Dark Rust
        "accent_color": (249, 115, 22),  # Flame Orange
        "tag": "#ExamSeason #AllNighter #Engineering"
    },
    {
        "id": "gigachad_flex",
        "title": "AVERAGE GROUP CHAT ENJOYER",
        "character": "Gigachad • Ernest Khalimov",
        "emoji": "🗿",
        "punchline": "Doesn't argue about anime powerscaling. Drops 'k' and sleeps for 11 hours. Pure Alpha.",
        "bg_color": (20, 20, 25),       # Dark Titanium
        "accent_color": (203, 213, 225), # Slate Silver
        "tag": "#Gigachad #SigmaGrind #NoDebates"
    },
    {
        "id": "cat_gamer_headset",
        "title": "3 AM COMPETITIVE GAMER",
        "character": "RGB Headset Cat • Hardstuck Silver",
        "emoji": "🎧",
        "punchline": "14 HP left, 1v4 clutch situation, whole dead squad screaming in 50 rupee mic 💀",
        "bg_color": (25, 15, 35),       # Cyber Dark
        "accent_color": (192, 132, 252), # Neon Lavender
        "tag": "#Valorant #BGMI #ClutchOrKick"
    },
    {
        "id": "spiderman_pointing",
        "title": "THE BLAME GAME",
        "character": "3 Spidermen Pointing",
        "emoji": "👉👈",
        "punchline": "acc1, acc2, and acc3 blaming each other after losing 13-0 in ranked match 😂",
        "bg_color": (15, 25, 40),       # Dark Cobalt
        "accent_color": (59, 130, 246),  # Electric Blue
        "tag": "#TrioSquad #BlameGame #Derank"
    },
    {
        "id": "light_potato_chip",
        "title": "I'LL TAKE A POTATO CHIP...",
        "character": "Light Yagami • Death Note",
        "emoji": "🥔",
        "punchline": "Me dramatic-eating 20-rupee Blue Lays at 2:30 AM while bingeing YouTube reels",
        "bg_color": (30, 20, 15),       # Dark Amber
        "accent_color": (234, 88, 12),   # Sunset Gold
        "tag": "#DeathNote #Lays #MidnightCraving"
    },
    {
        "id": "trade_offer_meme",
        "title": "TRADE OFFER!",
        "character": "TikTok Trade Offer Guy",
        "emoji": "🤝",
        "punchline": "You receive: Revive in blue zone. I receive: All your 5.56mm ammo & 8x scope.",
        "bg_color": (20, 30, 20),       # Tactical Camo
        "accent_color": (74, 222, 128),  # Mint Green
        "tag": "#BGMILoot #PUBGMobile #SquadTrade"
    }
]

def _get_font(size=24, bold=False):
    """Loads a suitable cross-platform TrueType font, falling back safely to default."""
    candidates = [
        "arialbd.ttf" if bold else "arial.ttf",
        "segoeuib.ttf" if bold else "segoeui.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"
    ]
    for c in candidates:
        try:
            return ImageFont.truetype(c, size)
        except Exception:
            pass
    return ImageFont.load_default()

def wrap_text(text, max_chars=34):
    """Wraps text into natural multiple lines for clean card rendering."""
    words = text.split()
    lines = []
    current_line = []
    current_len = 0
    for w in words:
        if current_len + len(w) + 1 > max_chars:
            lines.append(" ".join(current_line))
            current_line = [w]
            current_len = len(w)
        else:
            current_line.append(w)
            current_len += len(w) + 1
    if current_line:
        lines.append(" ".join(current_line))
    return lines

def generate_meme_card(meme_def, output_path):
    """Generates an ultra-crisp, dark-themed 640x640 meme card with Pillow."""
    width, height = 640, 640
    bg = meme_def.get("bg_color", (18, 18, 24))
    accent = meme_def.get("accent_color", (56, 189, 248))

    img = Image.new("RGB", (width, height), color=bg)
    draw = ImageDraw.Draw(img)

    # Outer border & header pill
    draw.rounded_rectangle([(16, 16), (width - 16, height - 16)], radius=24, outline=accent, width=4)
    draw.rounded_rectangle([(32, 32), (width - 32, 82)], radius=12, fill=(accent[0]//4, accent[1]//4, accent[2]//4), outline=accent, width=2)

    font_badge = _get_font(20, bold=True)
    draw.text((48, 44), "⚡ GENZETA OFFICIAL MEME DROP ⚡", fill=accent, font=font_badge)

    # Emoji & Title Banner
    font_emoji = _get_font(52, bold=True)
    draw.text((48, 115), meme_def.get("emoji", "🔥"), fill=(255, 255, 255), font=font_emoji)

    font_title = _get_font(28, bold=True)
    title_text = meme_def.get("title", "MEME")
    draw.text((120, 125), title_text, fill=(255, 255, 255), font=font_title)

    font_char = _get_font(18, bold=False)
    char_text = meme_def.get("character", "Unknown")
    draw.text((120, 165), char_text, fill=(180, 190, 205), font=font_char)

    # Central Divider line
    draw.line([(48, 205), (width - 48, 205)], fill=accent, width=2)

    # Punchline Content Box
    draw.rounded_rectangle([(40, 230), (width - 40, height - 110)], radius=18, fill=(10, 12, 16), outline=(60, 70, 85), width=2)

    font_punchline = _get_font(24, bold=True)
    raw_punchline = meme_def.get("punchline", "")
    lines = wrap_text(raw_punchline, max_chars=34)

    start_y = 265 + max(0, (260 - (len(lines) * 36)) // 2)
    for i, line in enumerate(lines):
        draw.text((65, start_y + (i * 38)), line, fill=(245, 245, 250), font=font_punchline)

    # Footer Tags & Bot Signature
    font_tag = _get_font(18, bold=True)
    draw.text((48, height - 75), meme_def.get("tag", "#AnimeMeme"), fill=accent, font=font_tag)

    font_footer = _get_font(16, bold=False)
    draw.text((width - 240, height - 73), "Gun Yamazaki • @genzetabot", fill=(120, 130, 145), font=font_footer)

    img.save(output_path, "PNG")
    return output_path

def ensure_all_memes_rendered():
    """Renders all catalog memes if they don't already exist on disk."""
    rendered = []
    for m in MEME_CATALOG:
        fn = f"{m['id']}.png"
        fpath = os.path.join(MEMES_DIR, fn)
        if not os.path.exists(fpath):
            generate_meme_card(m, fpath)
        rendered.append(fpath)
    return rendered

def get_random_meme():
    """Returns (filepath, meme_definition) for a random meme."""
    ensure_all_memes_rendered()
    # Check if there are any external custom images dropped in memes/
    all_files = [f for f in os.listdir(MEMES_DIR) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
    if not all_files:
        ensure_all_memes_rendered()
        all_files = [f for f in os.listdir(MEMES_DIR) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]

    chosen_file = random.choice(all_files)
    fpath = os.path.join(MEMES_DIR, chosen_file)

    # Match definition if available
    base_id = os.path.splitext(chosen_file)[0]
    matched = next((m for m in MEME_CATALOG if m['id'] == base_id), None)
    if not matched:
        matched = {
            "id": base_id,
            "title": base_id.replace("_", " ").title(),
            "punchline": "bhai ye meme dekh ke bilkul tum logo ki yaad aa gayi 😂",
            "tag": "#GenZetaMeme"
        }
    return fpath, matched

if __name__ == "__main__":
    print(f"Pre-rendering {len(MEME_CATALOG)} anime and gaming meme cards...")
    paths = ensure_all_memes_rendered()
    print(f"Successfully ensured {len(paths)} meme images in {MEMES_DIR}")
