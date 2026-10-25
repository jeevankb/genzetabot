import json
import os
import re
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)
STATE_FILE = os.path.join(DATA_DIR, "genzetabot_state.json")

# Default automated message frequency: 45.0 seconds (comfortably within 40-60s)
DEFAULT_AUTOMATION_SPEED = 45.0
DEFAULT_DELETE_DELAY = 900
DEFAULT_VOICE_REPLIES = True
DEFAULT_VOICE_COOLDOWN = 900.0     # 15 minutes default cooldown for automated voice notes
DEFAULT_VOICE_PROBABILITY = 0.025  # 2.5% default chance per turn

@dataclass
class GroupContext:
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
    # Multi-turn conversation memory (strictly isolated to this group)
    conversation_history: list = field(default_factory=list)
    # Voice note message IDs or history
    voice_history: list = field(default_factory=list)
    custom_settings: dict = field(default_factory=dict)
    state_msg_id: Optional[int] = None

    def add_history_turn(self, sender_name: str, role: str, text: str):
        """Adds a message turn to the group's isolated conversation memory."""
        self.conversation_history.append({
            "sender": sender_name,
            "role": role,
            "text": text
        })
        if len(self.conversation_history) > 20:
            self.conversation_history.pop(0)

    def get_recent_dialogue_context(self, max_turns: int = 6) -> str:
        """Formats the group's isolated multi-turn context for the LLM."""
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
    """Retrieves or creates an isolated GroupContext without overwriting custom settings."""
    if chat_id not in _group_cache:
        # Load from disk if available
        loaded = load_local_state().get(chat_id)
        if loaded:
            _group_cache[chat_id] = loaded
            if title and not _group_cache[chat_id].title:
                _group_cache[chat_id].title = title
        else:
            _group_cache[chat_id] = GroupContext(
                chat_id=chat_id,
                title=title or f"Chat_{chat_id}",
                automation_active=False,
                conversational_ai_active=True,
                speed=DEFAULT_AUTOMATION_SPEED,
                delete_delay=DEFAULT_DELETE_DELAY,
                voice_replies_enabled=DEFAULT_VOICE_REPLIES,
                csv_index=0
            )
    elif title and not _group_cache[chat_id].title:
        _group_cache[chat_id].title = title
    return _group_cache[chat_id]

def load_local_state() -> Dict[int, GroupContext]:
    """Loads all group contexts from persistent local JSON storage."""
    result = {}
    if not os.path.exists(STATE_FILE):
        return result
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
        logging.info(f"[Persistence] Loaded {len(result)} group contexts from local storage.")
    except Exception as e:
        logging.error(f"[Persistence] Error loading local state: {e}")
    return result

def save_local_state():
    """Flushes all in-memory group contexts to persistent local JSON storage."""
    try:
        payload = {}
        for cid, ctx in _group_cache.items():
            payload[str(cid)] = asdict(ctx)
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
                            logging.info(f"[Persistence] Restored cloud state for '{ctx.title}' ({cid}): auto={ctx.automation_active}, ai={ctx.conversational_ai_active}, speed={ctx.speed}s")
                    except Exception as pe:
                        logging.warning(f"[Persistence] Error parsing saved line: {pe}")
        save_local_state()
    except Exception as e:
        logging.error(f"[Persistence] Failed to restore from Telegram cloud: {e}")

def reset_group_state(chat_id: int):
    """Deliberately resets a group's configuration back to defaults if requested by admin."""
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
    logging.info(f"[Persistence] Deliberately reset state for group {chat_id}")
    return ctx
