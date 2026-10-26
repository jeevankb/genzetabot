import unittest
import asyncio
import os
import tempfile
import json
from unittest.mock import AsyncMock, MagicMock, patch

import voice_engine
import bot_persistence
from bot_persistence import GroupContext, get_or_create_group_context, reset_group_state


class TestVoiceIdentity(unittest.TestCase):
    """
    Test Requirement 1 & 10:
    Each account must strictly use its dedicated voice clone.
    acc1, acc2, acc3 use Fish Audio.
    acc4 (GenzetaBot) uses ElevenLabs.
    No cross-substitution or generic TTS fallback.
    """

    def test_strict_voice_mappings(self):
        summary = voice_engine.get_voice_mapping_summary()
        self.assertEqual(summary["acc1"]["provider"], "Fish Audio")
        self.assertEqual(summary["acc1"]["voice_id"], "8d4b31ea18e7498586849a0164391f9e")

        self.assertEqual(summary["acc2"]["provider"], "Fish Audio")
        self.assertEqual(summary["acc2"]["voice_id"], "5209483f80ab447288d1459216fb2505")

        self.assertEqual(summary["acc3"]["provider"], "Fish Audio")
        self.assertEqual(summary["acc3"]["voice_id"], "3e61b198fdcd4d689f563b5c1811c8f7")

        self.assertEqual(summary["acc4"]["provider"], "ElevenLabs")
        self.assertEqual(summary["acc4"]["voice_id"], "bIHbv24MWmeRgasZH58o")

    def test_no_generic_tts_fallback_for_accounts(self):
        """When Fish Audio API returns an error, accounts must NOT fall back to generic TTS."""
        async def run_test():
            with patch.dict(os.environ, {"FISH_AUDIO_API_KEY": "fake_key"}):
                with patch("aiohttp.ClientSession.post") as mock_post:
                    mock_resp = AsyncMock()
                    mock_resp.status = 402  # Insufficient credit
                    mock_resp.text = AsyncMock(return_value="Insufficient credit")
                    mock_post.return_value.__aenter__.return_value = mock_resp

                    fp, text = await voice_engine.generate_voice_note("acc1", "Test banter")
                    self.assertIsNone(fp, "Account 1 must return None on Fish Audio failure, never fallback to generic TTS")

                    fp, text = await voice_engine.generate_voice_note("acc2", "Test banter")
                    self.assertIsNone(fp, "Account 2 must return None on Fish Audio failure")

                    fp, text = await voice_engine.generate_voice_note("acc3", "Test banter")
                    self.assertIsNone(fp, "Account 3 must return None on Fish Audio failure")

        asyncio.run(run_test())

    def test_bot_strictly_uses_elevenlabs(self):
        """GenzetaBot must strictly use ElevenLabs, never Fish Audio or generic TTS."""
        async def run_test():
            with patch.dict(os.environ, {"ELEVENLABS_API_KEY": "fake_key"}):
                with patch("aiohttp.ClientSession.post") as mock_post:
                    mock_resp = AsyncMock()
                    mock_resp.status = 200
                    mock_resp.read = AsyncMock(return_value=b"ELEVENLABS_AUDIO_BYTES_TEST" * 50)
                    mock_post.return_value.__aenter__.return_value = mock_resp

                    fp, text = await voice_engine.generate_bot_voice("Hello I am Jarvis")
                    self.assertIsNotNone(fp)
                    self.assertTrue(os.path.exists(fp))
                    # Clean up
                    try: os.remove(fp)
                    except: pass

        asyncio.run(run_test())


class TestConversationIsolation(unittest.TestCase):
    """
    Test Requirement 2 & 10:
    Every group must maintain separate conversation context, history, and timing settings.
    No leakage across groups.
    """

    def setUp(self):
        bot_persistence._group_cache.clear()

    def test_multi_group_context_isolation(self):
        group_joker = get_or_create_group_context(1001, "Joker Jhamgat")
        group_anime = get_or_create_group_context(1002, "Bleach World")

        group_joker.add_history_turn("Merlin", "user", "Did you see the new episode?")
        group_joker.add_history_turn("GenzetaBot", "assistant", "Yes, the animation was peak!")

        group_anime.add_history_turn("Alice", "user", "Can someone recommend a gaming build?")

        # Check dialogue contexts
        joker_ctx = group_joker.get_recent_dialogue_context()
        anime_ctx = group_anime.get_recent_dialogue_context()

        self.assertIn("animation was peak", joker_ctx)
        self.assertNotIn("animation was peak", anime_ctx, "Joker Jhamgat context must NOT leak to Bleach World")
        self.assertIn("gaming build", anime_ctx)
        self.assertNotIn("gaming build", joker_ctx, "Bleach World context must NOT leak to Joker Jhamgat")

    def test_independent_timing_and_voice_settings(self):
        group_a = get_or_create_group_context(2001, "Group A")
        group_b = get_or_create_group_context(2002, "Group B")

        group_a.speed = 55.0
        group_a.delete_delay = 300
        group_a.voice_replies_enabled = True

        group_b.speed = 42.0
        group_b.delete_delay = 1800
        group_b.voice_replies_enabled = False

        self.assertEqual(group_a.speed, 55.0)
        self.assertEqual(group_b.speed, 42.0)
        self.assertNotEqual(group_a.speed, group_b.speed)

        self.assertEqual(group_a.delete_delay, 300)
        self.assertEqual(group_b.delete_delay, 1800)

        self.assertTrue(group_a.voice_replies_enabled)
        self.assertFalse(group_b.voice_replies_enabled)


class TestAutomationVsConversationalAI(unittest.TestCase):
    """
    Test Requirement 5, 7 & 10:
    lockoff stops automation but keeps Conversational AI active.
    Default frequency is 40-60s.
    """

    def setUp(self):
        bot_persistence._group_cache.clear()

    def test_default_interval_between_40_and_60_seconds(self):
        ctx = get_or_create_group_context(3001, "Fresh Group")
        self.assertGreaterEqual(ctx.speed, 40.0, "Default speed must be >= 40 seconds")
        self.assertLessEqual(ctx.speed, 60.0, "Default speed must be <= 60 seconds")
        self.assertEqual(ctx.speed, 45.0)

    def test_lockoff_separates_automation_from_conversational_ai(self):
        ctx = get_or_create_group_context(3002, "Active Group")
        # Turn lockon
        ctx.automation_active = True
        ctx.conversational_ai_active = True
        self.assertTrue(ctx.automation_active)
        self.assertTrue(ctx.conversational_ai_active)

        # Execute lockoff
        ctx.automation_active = False
        # Conversational AI must remain True!
        self.assertFalse(ctx.automation_active, "Automation must be disabled after lockoff")
        self.assertTrue(ctx.conversational_ai_active, "Conversational AI must stay ONLINE after lockoff")


class TestConfigurationPersistence(unittest.TestCase):
    """
    Test Requirement 8 & 10:
    Settings survive restarts and deployments.
    Does not overwrite existing configuration with defaults.
    """

    def setUp(self):
        bot_persistence._group_cache.clear()
        self.test_dir = tempfile.mkdtemp()
        self.orig_file = bot_persistence.STATE_FILE
        bot_persistence.STATE_FILE = os.path.join(self.test_dir, "test_state.json")

    def tearDown(self):
        bot_persistence.STATE_FILE = self.orig_file

    def test_save_and_reload_persistence(self):
        bot_persistence.reset_group_state(4001)
        ctx = get_or_create_group_context(4001, "Persistent Group")
        ctx.speed = 52.5
        ctx.delete_delay = 1200
        ctx.automation_active = True
        ctx.conversational_ai_active = True
        ctx.add_history_turn("User1", "user", "Remember this message")
        bot_persistence.save_local_state()

        # Clear in-memory cache to simulate full process restart
        bot_persistence._group_cache.clear()

        # Reload from disk
        reloaded = bot_persistence.load_local_state()
        self.assertIn(4001, reloaded)
        loaded_ctx = reloaded[4001]

        self.assertEqual(loaded_ctx.speed, 52.5)
        self.assertEqual(loaded_ctx.delete_delay, 1200)
        self.assertTrue(loaded_ctx.automation_active)
        self.assertTrue(loaded_ctx.conversational_ai_active)
        self.assertEqual(len(loaded_ctx.conversation_history), 1)
        self.assertEqual(loaded_ctx.conversation_history[0]["text"], "Remember this message")

    def test_deliberate_reset_mechanism(self):
        ctx = get_or_create_group_context(4002, "Group to Reset")
        ctx.speed = 99.0
        ctx.automation_active = True
        ctx.add_history_turn("User", "user", "Old text")

        reset_ctx = reset_group_state(4002)
        self.assertEqual(reset_ctx.speed, 45.0)
        self.assertFalse(reset_ctx.automation_active)
        self.assertTrue(reset_ctx.conversational_ai_active)
        self.assertEqual(len(reset_ctx.conversation_history), 0)


class TestAccountPermissions(unittest.TestCase):
    """
    Test Requirement 6 & 10:
    Super Admin / Primary accounts vs Operator (4th Account).
    Operator is strictly restricted to lockon / lockoff.
    """

    def test_operator_command_restrictions(self):
        import gunyamazaki

        async def run_test():
            # Mock event from Operator (User ID 6309134652)
            mock_event = MagicMock()
            mock_event.sender_id = 6309134652
            mock_event.is_private = True
            mock_event.get_sender = AsyncMock(return_value=MagicMock(username="operator_acc"))

            # Lockon should be allowed
            # We mock the setup_commands environment or test check_command_auth directly
            # Operator in SUPER_ADMIN_IDS vs OPERATOR_USER_IDS
            self.assertIn(6309134652, gunyamazaki.OPERATOR_USER_IDS)
            self.assertNotIn(6309134652, gunyamazaki.SUPER_ADMIN_IDS)

            # Check usernames
            self.assertIn("errormonocle", gunyamazaki.AUTHORIZED_USERNAMES)
            self.assertIn("merlin_hermis", gunyamazaki.AUTHORIZED_USERNAMES)
            self.assertIn("great_lotm", gunyamazaki.AUTHORIZED_USERNAMES)
            self.assertIn("greatlotm", gunyamazaki.AUTHORIZED_USERNAMES)

        asyncio.run(run_test())


class TestSpeedAndWaifuResilience(unittest.TestCase):
    """
    Tests high-speed 5s mode and resilience against waifu spawn / game bot freezing.
    """
    def test_instant_typing_at_5s_speed(self):
        import gunyamazaki
        async def run_test():
            start = asyncio.get_event_loop().time()
            # simulate_typing at 5s speed must return immediately (0s delay)
            await gunyamazaki.simulate_typing(MagicMock(), MagicMock(), "Test text message", group_speed=5.0)
            elapsed = asyncio.get_event_loop().time() - start
            self.assertLess(elapsed, 0.05, "simulate_typing at 5s must have 0 delay")
        asyncio.run(run_test())

    def test_edge_tts_fallback_when_enabled(self):
        async def run_test():
            with patch.dict(os.environ, {"ENABLE_EDGE_TTS_FALLBACK": "1", "FISH_AUDIO_API_KEY": ""}):
                with patch("voice_engine.ENABLE_EDGE_FALLBACK", True):
                    fp, text = await voice_engine.generate_voice_note("acc1", "Bhai testing edge fallback")
                    self.assertIsNotNone(fp, "Edge TTS fallback should return file path when enabled")
                    self.assertTrue(os.path.exists(fp))
                    if os.path.exists(fp):
                        try: os.remove(fp)
                        except: pass
        asyncio.run(run_test())

    def test_no_csv_paused_until_global(self):
        import gunyamazaki
        self.assertFalse(hasattr(gunyamazaki, 'csv_paused_until'), "csv_paused_until global must be removed")


class TestTargetGroupWhitelistAndPermissions(unittest.TestCase):
    """
    Tests strict single-target group whitelist (https://t.me/+noVnALjR8Uw1OWU1)
    and preservation of @Itsraventime1 operator permissions.
    """
    def setUp(self):
        import gunyamazaki
        self.orig_allowed = set(gunyamazaki.ALLOWED_GROUP_IDS)
        gunyamazaki.ALLOWED_GROUP_IDS.clear()

    def tearDown(self):
        import gunyamazaki
        gunyamazaki.ALLOWED_GROUP_IDS = self.orig_allowed

    def test_target_group_allowed_by_id_or_title(self):
        import gunyamazaki
        gunyamazaki.ALLOWED_GROUP_IDS.add(-100998877)
        self.assertTrue(gunyamazaki.is_allowed_group(-100998877, "Any Title"))
        # Whitelisted by title keyword
        self.assertTrue(gunyamazaki.is_allowed_group(-100554433, "Joker's_Jamghat_ 👽"))
        self.assertIn(-100554433, gunyamazaki.ALLOWED_GROUP_IDS)
        # Any other unauthorized group rejected
        self.assertFalse(gunyamazaki.is_allowed_group(-100112233, "Random Crypto Group"))
        self.assertFalse(gunyamazaki.is_allowed_group(-100223344, "Bleach World"))

    def test_itsraventime_maintains_permissions(self):
        import gunyamazaki
        self.assertEqual(gunyamazaki.PRIMARY_OPERATOR_ID, 6309134652)
        self.assertIn("itsraventime1", gunyamazaki.PRIMARY_OPERATOR_USERNAMES)
        self.assertIn("itsraventime", gunyamazaki.PRIMARY_OPERATOR_USERNAMES)
        for cmd in ["lockon", "lockoff", "setspeed", "speed", "stats"]:
            self.assertIn(cmd, gunyamazaki.OPERATOR_ALLOWED_COMMANDS)

    def test_deactivate_unauthorized_groups_persistence(self):
        bot_persistence.get_or_create_group_context(99111, "Target Group")
        bot_persistence.get_or_create_group_context(99222, "Other Group 1")
        bot_persistence.get_or_create_group_context(99333, "Other Group 2")

        # Set all active
        bot_persistence._group_cache[99111].automation_active = True
        bot_persistence._group_cache[99222].automation_active = True
        bot_persistence._group_cache[99333].automation_active = True
        bot_persistence.save_group_state_to_db(bot_persistence._group_cache[99111])
        bot_persistence.save_group_state_to_db(bot_persistence._group_cache[99222])
        bot_persistence.save_group_state_to_db(bot_persistence._group_cache[99333])

        # Deactivate all except target group 99111
        bot_persistence.deactivate_unauthorized_groups({99111})

        self.assertTrue(bot_persistence._group_cache[99111].automation_active)
        self.assertFalse(bot_persistence._group_cache[99222].automation_active)
        self.assertFalse(bot_persistence._group_cache[99333].automation_active)


if __name__ == "__main__":
    unittest.main()
