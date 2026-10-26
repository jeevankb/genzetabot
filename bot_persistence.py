import json
import os
import re
import sqlite3
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List, Tuple

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)
STATE_FILE = os.path.join(DATA_DIR, "genzetabot_state.json")
DB_FILE = os.path.join(DATA_DIR, "genzetabot.db")

# Default automated message frequency: 45.0 seconds (comfortably within 40-60s)
DEFAULT_AUTOMATION_SPEED = 45.0
DEFAULT_DELETE_DELAY = 900
DEFAULT_VOICE_REPLIES = True
DEFAULT_VOICE_COOLDOWN = 900.0     # 15 minutes default cooldown for automated voice notes
DEFAULT_VOICE_PROBABILITY = 0.025  # 2.5% default chance per turn

# ---------------------------------------------------------------------------
# SQLITE DATABASE INITIALIZATION (ACID Transactions & Indexed B-Trees)
# ---------------------------------------------------------------------------
def _get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

def init_db():
    """Initializes SQLite schema for group configurations and conversation history."""
    try:
        with _get_db_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS group_settings (
                    chat_id INTEGER PRIMARY KEY,
                    title TEXT,
                    automation_active INTEGER DEFAULT 0,
                    conversational_ai_active INTEGER DEFAULT 1,
                    speed REAL DEFAULT 45.0,
                    delete_delay INTEGER DEFAULT 900,
                    voice_replies_enabled INTEGER DEFAULT 1,
                    voice_cooldown REAL DEFAULT 900.0,
                    voice_probability REAL DEFAULT 0.025,
                    csv_index INTEGER DEFAULT 0,
                    active_day_name TEXT DEFAULT '',
                    state_msg_id INTEGER,
                    updated_at REAL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS group_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    sender TEXT NOT NULL,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    timestamp REAL NOT NULL
                );
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_group_history_chat_id_id 
                ON group_history(chat_id, id DESC);
            """)
        logging.info("[Persistence] SQLite database initialized successfully (WAL mode enabled).")
    except Exception as e:
        logging.error(f"[Persistence] Failed to initialize SQLite schema: {e}")

# Run schema initialization on module import
init_db()

@dataclass
class GroupContext:
    """
    Isolated configuration and multi-turn conversational context for a single group.
    Maintains complete isolation from all other groups.
    """
    chat_id: int
    title: str = ""
    # Automation state (controlled by lockon / lockoff)
    automation_active: bool = False
    # Conversational AI state (Jarvis Q&A, active independently of lock state!)
    conversational_ai_active: bool = True
    speed: float = DEFAULT_AUTOMATION_SPEED
    delete_delay: int = DEFAULT_DELETE_DELAY
    voice_replies_enabled: bool = DEFAULT_VOICE_REPLIES
    voice_cooldown: float = DEFAULT_VOICE_COOLDOWN
    voice_probability: float = DEFAULT_VOICE_PROBABILITY
    csv_index: int = 0
    active_day_name: str = ""
    # In-memory bounded multi-turn conversation memory
    conversation_history: list = field(default_factory=list)
    voice_history: list = field(default_factory=list)
    custom_settings: dict = field(default_factory=dict)
    state_msg_id: Optional[int] = None

    def add_history_turn(self, sender_name: str, role: str, text: str):
        """
        Appends a conversation turn both to in-memory deque and to indexed SQLite table.
        Time Complexity: O(1) in-memory append + O(log n) B-Tree SQLite index insertion.
        Space Complexity: O(1) per turn.
        """
        turn_data = {
            "sender": sender_name,
            "role": role,
            "text": text
        }
        self.conversation_history.append(turn_data)
        if len(self.conversation_history) > 20:
            self.conversation_history.pop(0)

        # Persist to SQLite table
        try:
            with _get_db_connection() as conn:
                conn.execute(
                    "INSERT INTO group_history (chat_id, sender, role, text, timestamp) VALUES (?, ?, ?, ?, ?)",
                    (self.chat_id, sender_name, role, text, time.time())
                )
        except Exception as e:
            logging.debug(f"[Persistence] SQLite history insert failed for {self.chat_id}: {e}")

    def get_recent_dialogue_context(self, max_turns: int = 6) -> str:
        """
        Retrieves the most recent k conversation turns using indexed SQLite query or in-memory cache.
        Time Complexity: O(log n + k) via B-Tree index (chat_id, id DESC).
        Space Complexity: O(k) bounded by max_turns.
        """
        try:
            with _get_db_connection() as conn:
                cur = conn.execute(
                    "SELECT sender, text FROM group_history WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
                    (self.chat_id, max_turns)
                )
                rows = cur.fetchall()
                if rows:
                    lines = [f"{r['sender']}: {r['text']}" for r in reversed(rows)]
                    return "\n".join(lines)
        except Exception:
            pass

        # In-memory fallback
        recent = self.conversation_history[-max_turns:]
        if not recent:
            return "(No previous conversation in this group)"
        lines = []
        for turn in recent:
            sender = turn.get("sender", "User")
            text = turn.get("text", "")
            lines.append(f"{sender}: {text}")
        return "\n".join(lines)

_group_cache: Dict[int, GroupContext] = {}

def get_or_create_group_context(chat_id: int, title: str = "") -> GroupContext:
    """
    Retrieves or creates an isolated GroupContext.
    Time Complexity: O(1) hash map lookup.
    Never overwrites custom group settings with defaults on load.
    """
    if chat_id not in _group_cache:
        # 1. Try loading from SQLite
        loaded_ctx = _load_group_from_sqlite(chat_id)
        if loaded_ctx:
            _group_cache[chat_id] = loaded_ctx
            if title and not _group_cache[chat_id].title:
                _group_cache[chat_id].title = title
        else:
            # 2. Try loading from JSON fallback
            all_local = load_local_state()
            if chat_id in all_local:
                _group_cache[chat_id] = all_local[chat_id]
                if title and not _group_cache[chat_id].title:
                    _group_cache[chat_id].title = title
            else:
                # 3. Create fresh context with defaults (never overwrite existing)
                _group_cache[chat_id] = GroupContext(
                    chat_id=chat_id,
                    title=title or f"Chat_{chat_id}",
                    automation_active=False,
                    conversational_ai_active=True,
                    speed=DEFAULT_AUTOMATION_SPEED,
                    delete_delay=DEFAULT_DELETE_DELAY,
                    voice_replies_enabled=DEFAULT_VOICE_REPLIES,
                    voice_cooldown=DEFAULT_VOICE_COOLDOWN,
                    voice_probability=DEFAULT_VOICE_PROBABILITY,
                    csv_index=0
                )
                save_group_state_to_db(_group_cache[chat_id])
    elif title and not _group_cache[chat_id].title:
        _group_cache[chat_id].title = title
    return _group_cache[chat_id]

def _load_group_from_sqlite(chat_id: int) -> Optional[GroupContext]:
    try:
        with _get_db_connection() as conn:
            cur = conn.execute("SELECT * FROM group_settings WHERE chat_id = ?", (chat_id,))
            row = cur.fetchone()
            if row:
                ctx = GroupContext(
                    chat_id=row["chat_id"],
                    title=row["title"] or f"Chat_{row['chat_id']}",
                    automation_active=bool(row["automation_active"]),
                    conversational_ai_active=bool(row["conversational_ai_active"]),
                    speed=float(row["speed"]),
                    delete_delay=int(row["delete_delay"]),
                    voice_replies_enabled=bool(row["voice_replies_enabled"]),
                    voice_cooldown=float(row["voice_cooldown"]),
                    voice_probability=float(row["voice_probability"]),
                    csv_index=int(row["csv_index"]),
                    active_day_name=row["active_day_name"] or "",
                    state_msg_id=row["state_msg_id"]
                )
                # Load recent history
                h_cur = conn.execute(
                    "SELECT sender, role, text FROM group_history WHERE chat_id = ? ORDER BY id DESC LIMIT 20",
                    (chat_id,)
                )
                h_rows = h_cur.fetchall()
                ctx.conversation_history = [
                    {"sender": r["sender"], "role": r["role"], "text": r["text"]}
                    for r in reversed(h_rows)
                ]
                return ctx
    except Exception as e:
        logging.debug(f"[Persistence] SQLite load error for {chat_id}: {e}")
    return None

def save_group_state_to_db(ctx: GroupContext):
    """Saves a group context atomically to SQLite."""
    try:
        with _get_db_connection() as conn:
            conn.execute("""
                INSERT INTO group_settings (
                    chat_id, title, automation_active, conversational_ai_active,
                    speed, delete_delay, voice_replies_enabled, voice_cooldown,
                    voice_probability, csv_index, active_day_name, state_msg_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    title=excluded.title,
                    automation_active=excluded.automation_active,
                    conversational_ai_active=excluded.conversational_ai_active,
                    speed=excluded.speed,
                    delete_delay=excluded.delete_delay,
                    voice_replies_enabled=excluded.voice_replies_enabled,
                    voice_cooldown=excluded.voice_cooldown,
                    voice_probability=excluded.voice_probability,
                    csv_index=excluded.csv_index,
                    active_day_name=excluded.active_day_name,
                    state_msg_id=excluded.state_msg_id,
                    updated_at=excluded.updated_at;
            """, (
                ctx.chat_id, ctx.title, int(ctx.automation_active), int(ctx.conversational_ai_active),
                ctx.speed, ctx.delete_delay, int(ctx.voice_replies_enabled), ctx.voice_cooldown,
                ctx.voice_probability, ctx.csv_index, ctx.active_day_name, ctx.state_msg_id, time.time()
            ))
    except Exception as e:
        logging.warning(f"[Persistence] SQLite save error for {ctx.chat_id}: {e}")

def load_local_state() -> Dict[int, GroupContext]:
    """Loads all group contexts from persistent SQLite database (fallback to JSON)."""
    result = {}
    # 1. Try SQLite first
    try:
        with _get_db_connection() as conn:
            cur = conn.execute("SELECT * FROM group_settings")
            rows = cur.fetchall()
            for r in rows:
                cid = r["chat_id"]
                ctx = GroupContext(
                    chat_id=cid,
                    title=r["title"] or f"Chat_{cid}",
                    automation_active=bool(r["automation_active"]),
                    conversational_ai_active=bool(r["conversational_ai_active"]),
                    speed=float(r["speed"]),
                    delete_delay=int(r["delete_delay"]),
                    voice_replies_enabled=bool(r["voice_replies_enabled"]),
                    voice_cooldown=float(r["voice_cooldown"]),
                    voice_probability=float(r["voice_probability"]),
                    csv_index=int(r["csv_index"]),
                    active_day_name=r["active_day_name"] or "",
                    state_msg_id=r["state_msg_id"]
                )
                # Load recent conversation history for this group from SQLite
                h_cur = conn.execute(
                    "SELECT sender, role, text FROM group_history WHERE chat_id = ? ORDER BY id DESC LIMIT 20",
                    (cid,)
                )
                ctx.conversation_history = [
                    {"sender": hr["sender"], "role": hr["role"], "text": hr["text"]}
                    for hr in reversed(h_cur.fetchall())
                ]
                result[cid] = ctx
                _group_cache[cid] = ctx
        if result:
            logging.info(f"[Persistence] Loaded {len(result)} group contexts from SQLite database.")
            return result
    except Exception as e:
        logging.debug(f"[Persistence] SQLite bulk load error: {e}")

    # 2. Fallback to JSON file
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for cid_str, gdata in data.items():
                cid = int(cid_str)
                ctx = GroupContext(
                    chat_id=cid,
                    title=gdata.get("title", f"Chat_{cid}"),
                    automation_active=bool(gdata.get("automation_active", False)),
                    conversational_ai_active=bool(gdata.get("conversational_ai_active", True)),
                    speed=float(gdata.get("speed", DEFAULT_AUTOMATION_SPEED)),
                    delete_delay=int(gdata.get("delete_delay", DEFAULT_DELETE_DELAY)),
                    voice_replies_enabled=bool(gdata.get("voice_replies_enabled", True)),
                    voice_cooldown=float(gdata.get("voice_cooldown", DEFAULT_VOICE_COOLDOWN)),
                    voice_probability=float(gdata.get("voice_probability", DEFAULT_VOICE_PROBABILITY)),
                    csv_index=int(gdata.get("csv_index", 0)),
                    active_day_name=gdata.get("active_day_name", ""),
                    conversation_history=gdata.get("conversation_history", []),
                    voice_history=gdata.get("voice_history", []),
                    custom_settings=gdata.get("custom_settings", {}),
                    state_msg_id=gdata.get("state_msg_id")
                )
                result[cid] = ctx
                _group_cache[cid] = ctx
                save_group_state_to_db(ctx)
            logging.info(f"[Persistence] Loaded {len(result)} group contexts from JSON and migrated to SQLite.")
        except Exception as e:
            logging.error(f"[Persistence] Error loading JSON state: {e}")
    return result

def save_local_state():
    """Flushes all in-memory group contexts to SQLite database and persistent JSON backup."""
    try:
        payload = {}
        for cid, ctx in _group_cache.items():
            payload[str(cid)] = asdict(ctx)
            save_group_state_to_db(ctx)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error(f"[Persistence] Error saving local state: {e}")

async def sync_group_to_telegram_cloud(client, chat_id: int):
    """
    Backs up group context to Telegram Saved Messages ('me').
    Ensures persistent cloud recovery across fresh container redeployments.
    """
    if not client:
        return
    try:
        ctx = get_or_create_group_context(chat_id)
        clean_title = (ctx.title or f"Chat_{chat_id}").replace(" ", "_")
        text = (
            f"[GenzetaGroupState {chat_id}] "
            f"auto={1 if ctx.automation_active else 0} "
            f"ai={1 if ctx.conversational_ai_active else 0} "
            f"speed={ctx.speed} "
            f"del={ctx.delete_delay} "
            f"voice={1 if ctx.voice_replies_enabled else 0} "
            f"vcd={int(ctx.voice_cooldown)} "
            f"vprob={ctx.voice_probability} "
            f"csv={ctx.csv_index} "
            f"day={ctx.active_day_name} "
            f"title={clean_title}"
        )
        if ctx.state_msg_id:
            try:
                await client.edit_message("me", ctx.state_msg_id, text)
                save_local_state()
                return
            except Exception:
                pass
        msg = await client.send_message("me", text)
        ctx.state_msg_id = msg.id
        save_local_state()
    except Exception as e:
        logging.warning(f"[Persistence] Failed to sync group {chat_id} to Telegram Saved Messages: {e}")

async def restore_from_telegram_cloud(client):
    """
    Restores group states from Telegram Saved Messages.
    Iterates without MTProto search query filter to avoid punctuation stripping issues.
    """
    if not client:
        return
    try:
        async for msg in client.iter_messages("me", limit=150):
            if not msg.text:
                continue
            for line in msg.text.splitlines():
                if "[GenzetaGroupState" in line or "[GunYamazaki GroupState" in line:
                    try:
                        m = re.search(r'\[(?:GenzetaGroupState|GunYamazaki GroupState)\s+(-?\d+)\]\s*(.*)', line)
                        if m:
                            cid = int(m.group(1))
                            ctx = get_or_create_group_context(cid)
                            ctx.state_msg_id = msg.id
                            props = m.group(2)
                            for item in props.split():
                                if "=" in item:
                                    k, v = item.split("=", 1)
                                    if k in ("auto", "active"):
                                        ctx.automation_active = (v in ("1", "true", "True"))
                                    elif k == "ai":
                                        ctx.conversational_ai_active = (v in ("1", "true", "True"))
                                    elif k == "speed":
                                        ctx.speed = float(v)
                                    elif k in ("del", "delete_delay"):
                                        ctx.delete_delay = int(v)
                                    elif k == "voice":
                                        ctx.voice_replies_enabled = (v in ("1", "true", "True"))
                                    elif k == "vcd":
                                        ctx.voice_cooldown = float(v)
                                    elif k == "vprob":
                                        ctx.voice_probability = float(v)
                                    elif k == "csv":
                                        ctx.csv_index = int(v)
                                    elif k == "day":
                                        ctx.active_day_name = v.lower()
                                    elif k == "title":
                                        ctx.title = v.replace("_", " ")
                            save_group_state_to_db(ctx)
                            logging.info(f"[Persistence] Restored cloud state for '{ctx.title}' ({cid}): auto={ctx.automation_active}, ai={ctx.conversational_ai_active}, speed={ctx.speed}s")
                    except Exception as pe:
                        logging.warning(f"[Persistence] Error parsing saved line: {pe}")
        save_local_state()
    except Exception as e:
        logging.error(f"[Persistence] Failed to restore from Telegram cloud: {e}")

def reset_group_state(chat_id: int):
    """Deliberately resets a group's configuration back to defaults if requested by super admin."""
    ctx = get_or_create_group_context(chat_id)
    ctx.automation_active = False
    ctx.conversational_ai_active = True
    ctx.speed = DEFAULT_AUTOMATION_SPEED
    ctx.delete_delay = DEFAULT_DELETE_DELAY
    ctx.voice_replies_enabled = DEFAULT_VOICE_REPLIES
    ctx.voice_cooldown = DEFAULT_VOICE_COOLDOWN
    ctx.voice_probability = DEFAULT_VOICE_PROBABILITY
    ctx.csv_index = 0
    ctx.conversation_history.clear()
    ctx.voice_history.clear()
    save_local_state()
    try:
        with _get_db_connection() as conn:
            conn.execute("DELETE FROM group_history WHERE chat_id = ?", (chat_id,))
    except Exception:
        pass
    logging.info(f"[Persistence] Deliberately reset state for group {chat_id}")
    return ctx

def deactivate_unauthorized_groups(allowed_chat_ids: set):
    """
    Deactivates automation for all groups except the explicitly allowed group.
    Ensures that no other group retains automation permissions in SQLite or memory.
    """
    if not allowed_chat_ids:
        return
    try:
        with _get_db_connection() as conn:
            placeholders = ",".join("?" for _ in allowed_chat_ids)
            conn.execute(f"""
                UPDATE group_settings
                SET automation_active = 0
                WHERE chat_id NOT IN ({placeholders})
            """, tuple(allowed_chat_ids))
        for cid, ctx in list(_group_cache.items()):
            if cid not in allowed_chat_ids:
                ctx.automation_active = False
        save_local_state()
        logging.info(f"[Persistence] Successfully revoked automation for all groups except allowed IDs: {allowed_chat_ids}")
    except Exception as e:
        logging.error(f"[Persistence] Error deactivating unauthorized groups: {e}")

