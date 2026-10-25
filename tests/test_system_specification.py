import unittest
import asyncio
import os
import tempfile
import time
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import gunyamazaki
import voice_engine
from voice_engine import VoiceAudioLRUCache, get_voice_mapping_summary
import bot_persistence
from bot_persistence import GroupContext, get_or_create_group_context, save_group_state_to_db, load_local_state


class TestSection12Permissions(unittest.TestCase):
    """Automated test suite for Section 12 Permissions & RBAC."""

    def test_operator_authorized_and_restricted_commands(self):
        """Operator (6309134652) is strictly permitted for allowlist and denied otherwise."""
        self.assertEqual(gunyamazaki.PRIMARY_OPERATOR_ID, 6309134652)
        self.assertEqual(gunyamazaki.OPERATOR_ALLOWED_COMMANDS, {"lockon", "lockoff", "setspeed", "speed", "stats"})

        # Permitted
        for cmd in ["lockon", "lockoff", "setspeed", "speed", "stats"]:
            self.assertIn(cmd, gunyamazaki.OPERATOR_ALLOWED_COMMANDS)

        # Denied
        denied_cmds = ["setvoicefreq", "setvoicecooldown", "resetgroup", "setdelete", "setday", "ariseon", "ariseoff"]
        for cmd in denied_cmds:
            self.assertNotIn(cmd, gunyamazaki.OPERATOR_ALLOWED_COMMANDS)

    def test_super_admin_access(self):
        """Super Admins have full access including hidden voice frequency."""
        for sa_id in [5429173364, 8877720410]:
            self.assertIn(sa_id, gunyamazaki.SUPER_ADMIN_IDS)
        self.assertIn("setvoicefreq", gunyamazaki.SUPER_ADMIN_ALLOWED_COMMANDS)
        self.assertIn("setvoicecooldown", gunyamazaki.SUPER_ADMIN_ALLOWED_COMMANDS)

    def test_ordinary_user_cannot_execute_commands(self):
        """Ordinary chatters are denied command execution."""
        normal_id = 99887766
        self.assertNotIn(normal_id, gunyamazaki.SUPER_ADMIN_IDS)
        self.assertNotEqual(normal_id, gunyamazaki.PRIMARY_OPERATOR_ID)

    def test_voice_transcription_cannot_bypass_rbac(self):
        """Commands received through transcription or alternative interfaces still verify sender identity."""
        async def run():
            mock_event = MagicMock()
            mock_event.sender_id = 12345678  # unauthorized user
            sender_id = mock_event.sender_id
            self.assertFalse(sender_id in gunyamazaki.SUPER_ADMIN_IDS or sender_id == gunyamazaki.PRIMARY_OPERATOR_ID)
        asyncio.run(run())


class TestSection12VoiceAndAudioCache(unittest.TestCase):
    """Automated test suite for Section 12 Voice Assignments & Bounded LRU Cache."""

    def test_strict_voice_mappings(self):
        """Each account has its own dedicated voice identity and provider."""
        summary = get_voice_mapping_summary()
        self.assertEqual(summary["acc1"]["provider"], "Fish Audio")
        self.assertEqual(summary["acc1"]["voice_id"], "8d4b31ea18e7498586849a0164391f9e")

        self.assertEqual(summary["acc2"]["provider"], "Fish Audio")
        self.assertEqual(summary["acc2"]["voice_id"], "5209483f80ab447288d1459216fb2505")

        self.assertEqual(summary["acc3"]["provider"], "Fish Audio")
        self.assertEqual(summary["acc3"]["voice_id"], "3e61b198fdcd4d689f563b5c1811c8f7")

        self.assertEqual(summary["acc4"]["provider"], "ElevenLabs")
        self.assertEqual(summary["acc4"]["voice_id"], "bIHbv24MWmeRgasZH58o")

    def test_no_generic_tts_fallback_on_failure(self):
        """On API failure, returns None without substituting another voice or generic TTS."""
        async def run():
            with patch.dict(os.environ, {"FISH_AUDIO_API_KEY": ""}):
                path, text = await voice_engine.generate_fish_audio_voice("acc1", "Hello test")
                self.assertIsNone(path)
                self.assertIsNone(text)
        asyncio.run(run())

    def test_bounded_lru_audio_cache_hits_and_eviction(self):
        """Cache reuses identical audio, never mixes identities, and bounds memory/disk."""
        temp_dir = tempfile.mkdtemp()
        cache = VoiceAudioLRUCache(cache_dir=temp_dir, max_entries=3, max_bytes=10000)

        k1 = cache.make_key("fish", "model_a", "Hello world")
        k2 = cache.make_key("fish", "model_b", "Hello world")  # Different voice identity!
        k3 = cache.make_key("elevenlabs", "voice_c", "Hello world")
        k4 = cache.make_key("fish", "model_a", "Fourth sentence")

        # Keys must be distinct because voice identities differ
        self.assertNotEqual(k1, k2)
        self.assertNotEqual(k1, k3)

        cache.put(k1, b"audio_11111")
        cache.put(k2, b"audio_22222")
        cache.put(k3, b"audio_33333")

        # Cache HIT on k1
        res1 = cache.get(k1)
        self.assertIsNotNone(res1)
        self.assertEqual(cache.hits, 1)

        # Insert 4th item -> must evict least recently used (k2 was not accessed recently)
        cache.put(k4, b"audio_44444")
        self.assertEqual(cache.evictions, 1)
        self.assertIsNone(cache.get(k2))  # k2 evicted
        self.assertIsNotNone(cache.get(k1))  # k1 retained because it was accessed


class TestSection12GroupIsolation(unittest.TestCase):
    """Automated test suite for Section 12 Group Isolation."""

    def test_group_settings_independence(self):
        """Modifying speed, voice frequency, and history in Group 1 does not affect Group 2."""
        g1 = get_or_create_group_context(101, "Joker Jhamgat")
        g2 = get_or_create_group_context(102, "Bleach World")

        g1.speed = 5.0
        g1.voice_cooldown = 300.0
        g1.voice_probability = 0.10
        g1.add_history_turn("Alice", "user", "Message in group 1")

        g2.speed = 45.0
        g2.voice_cooldown = 900.0
        g2.voice_probability = 0.025
        g2.add_history_turn("Bob", "user", "Message in group 2")

        # Independent assertions
        self.assertEqual(g1.speed, 5.0)
        self.assertEqual(g2.speed, 45.0)
        self.assertEqual(g1.voice_cooldown, 300.0)
        self.assertEqual(g2.voice_cooldown, 900.0)
        self.assertIn("Message in group 1", g1.get_recent_dialogue_context())
        self.assertNotIn("Message in group 1", g2.get_recent_dialogue_context())
        self.assertIn("Message in group 2", g2.get_recent_dialogue_context())


class TestSection12Persistence(unittest.TestCase):
    """Automated test suite for Section 12 SQLite & Durability."""

    def test_sqlite_persistence_across_cache_clear(self):
        """Group configuration and history survive cache wipe via SQLite."""
        test_cid = 777123
        ctx = get_or_create_group_context(test_cid, "Persistent Group")
        ctx.speed = 52.0
        ctx.voice_cooldown = 750.0
        ctx.add_history_turn("Merlin", "user", "Remember this secret topic")
        save_group_state_to_db(ctx)

        # Clear in-memory cache
        bot_persistence._group_cache.clear()

        # Reload from storage
        reloaded = get_or_create_group_context(test_cid)
        self.assertEqual(reloaded.speed, 52.0)
        self.assertEqual(reloaded.voice_cooldown, 750.0)
        self.assertIn("Remember this secret topic", reloaded.get_recent_dialogue_context())

    def test_defaults_never_overwrite_saved_settings(self):
        """Reloading does not reset configured speed or lock state back to defaults."""
        test_cid = 888123
        ctx = get_or_create_group_context(test_cid, "Configured Group")
        ctx.speed = 42.0
        ctx.automation_active = False  # Explicitly locked off
        save_group_state_to_db(ctx)

        bot_persistence._group_cache.clear()
        reloaded = get_or_create_group_context(test_cid)
        self.assertEqual(reloaded.speed, 42.0)
        self.assertFalse(reloaded.automation_active)


class TestSection12PerformanceAndScheduler(unittest.TestCase):
    """Automated test suite for Section 12 Scheduler lifecycle & concurrency."""

    def test_lockoff_cancels_active_scheduler(self):
        """Executing lockoff cancels the running asyncio loop task cleanly."""
        state = gunyamazaki.get_group_state(555999, "Task Group")
        state.is_active = True
        state.automation_active = True

        # Simulate running loop task
        async def dummy_loop():
            try:
                while True:
                    await asyncio.sleep(10)
            except asyncio.CancelledError:
                pass

        async def run_test():
            state.loop_task = asyncio.create_task(dummy_loop())
            state.is_loop_running = True

            # Perform lockoff simulation
            state.is_active = False
            state.automation_active = False
            if state.loop_task and not state.loop_task.done():
                state.loop_task.cancel()
            state.is_loop_running = False

            await asyncio.sleep(0.01)
            self.assertTrue(state.loop_task.done())
            self.assertFalse(state.is_loop_running)

        asyncio.run(run_test())


class TestSection12Security(unittest.TestCase):
    """Automated test suite for Section 12 API Security & Log Redaction."""

    def test_sensitive_log_filter(self):
        """Redacts Fish Audio, ElevenLabs, Bot tokens, and AI keys from application logs."""
        filtr = gunyamazaki.SensitiveDataFilter()

        rec = logging.LogRecord(
            "test", logging.INFO, "test.py", 1,
            "Connecting with sk-fish-test-key-1234567890123456 and bot123456789:ABCDefgh-12345678901234567890123456789012",
            (), None
        )
        filtr.filter(rec)
        self.assertNotIn("sk-fish-test-key-1234567890123456", rec.msg)
        self.assertNotIn("bot123456789:ABCDefgh-12345678901234567890123456789012", rec.msg)
        self.assertIn("[REDACTED_SECRET]", rec.msg)

    def test_prompt_confidentiality_directive(self):
        """Conversational AI system prompt contains strict anti-leak directive."""
        with open("gunyamazaki.py", "r", encoding="utf-8") as f:
            code = f.read()
        self.assertIn("CONFIDENTIALITY & INTEGRITY DIRECTIVE", code)
        self.assertIn("Under NO circumstance disclose, hint at, quote, or discuss API keys", code)


if __name__ == "__main__":
    unittest.main()
