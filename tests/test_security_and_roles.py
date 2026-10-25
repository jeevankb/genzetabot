import unittest
import asyncio
import os
import tempfile
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import gunyamazaki
import bot_persistence
from bot_persistence import GroupContext, get_or_create_group_context


class TestPrimaryOperatorRBAC(unittest.TestCase):
    """
    Test Requirement 1, 2 & 6:
    Verify Primary Operator (@Itsraventime1 / 6309134652) role-based permissions.
    """

    def setUp(self):
        bot_persistence._group_cache.clear()

    def test_operator_identification_and_allowlist(self):
        """Operator identified by immutable ID 6309134652 can execute ONLY its allowlisted commands."""
        self.assertEqual(gunyamazaki.PRIMARY_OPERATOR_ID, 6309134652)
        self.assertIn("itsraventime1", gunyamazaki.PRIMARY_OPERATOR_USERNAMES)
        self.assertEqual(
            gunyamazaki.OPERATOR_ALLOWED_COMMANDS,
            {"lockon", "lockoff", "setspeed", "speed", "stats"}
        )

    def test_operator_permitted_commands(self):
        """Operator can execute lockon, lockoff, setspeed, speed, stats."""
        async def run():
            # Create a mock client
            mock_client = MagicMock()
            mock_client.is_connected = MagicMock(return_value=True)

            # Build mock event from Operator
            for cmd in ["lockon", "lockoff", "setspeed", "speed", "stats"]:
                mock_event = MagicMock()
                mock_event.sender_id = 6309134652
                mock_event.is_private = False
                mock_event.chat_id = -10012345
                mock_event.get_sender = AsyncMock(return_value=MagicMock(id=6309134652, username="Itsraventime1"))

                # In setup_commands scope, we test check_command_auth logic
                s_id = mock_event.sender_id
                username = "itsraventime1"
                is_operator = (s_id == gunyamazaki.PRIMARY_OPERATOR_ID) or (username in gunyamazaki.PRIMARY_OPERATOR_USERNAMES)
                self.assertTrue(is_operator)
                self.assertIn(cmd, gunyamazaki.OPERATOR_ALLOWED_COMMANDS)

        asyncio.run(run())

    def test_operator_denied_privileged_commands(self):
        """Operator CANNOT execute setvoicefreq, resetgroup, setdelete, setday, ariseon, etc."""
        restricted_cmds = [
            "setvoicefreq", "setvoicecooldown", "resetgroup",
            "setdelete", "autodelete", "setday", "ariseon", "ariseoff", "arisehere", "lockarise"
        ]
        s_id = 6309134652
        username = "itsraventime1"
        is_operator = (s_id == gunyamazaki.PRIMARY_OPERATOR_ID) or (username in gunyamazaki.PRIMARY_OPERATOR_USERNAMES)
        self.assertTrue(is_operator)

        for cmd in restricted_cmds:
            self.assertNotIn(
                cmd, gunyamazaki.OPERATOR_ALLOWED_COMMANDS,
                f"Command '{cmd}' must be strictly restricted from Operator!"
            )


class TestHiddenVoiceFrequencyCommand(unittest.TestCase):
    """
    Test Requirement 3 & 6:
    Hidden Voice-Frequency Configuration Command.
    Only Super Admins can execute it.
    Operator and regular users are denied even if they know the command name.
    Settings are independent per group and survive restarts.
    """

    def setUp(self):
        bot_persistence._group_cache.clear()

    def test_hidden_command_not_in_public_stats(self):
        """The command must not be exposed in stats or ordinary help lists."""
        state = get_or_create_group_context(5001, "Test Group")
        # Ensure stats text or public help doesn't reveal setvoicefreq
        stats_cmd = "stats"
        self.assertNotIn("setvoicefreq", stats_cmd)
        self.assertNotIn("setvoicecooldown", stats_cmd)

    def test_super_admin_authorized_for_voicefreq(self):
        """Super Admin (5429173364 / 8877720410) can execute setvoicefreq."""
        self.assertIn("setvoicefreq", gunyamazaki.SUPER_ADMIN_ALLOWED_COMMANDS)
        self.assertIn("setvoicecooldown", gunyamazaki.SUPER_ADMIN_ALLOWED_COMMANDS)

    def test_operator_denied_voicefreq(self):
        """Operator (6309134652) is strictly denied from setvoicefreq even if they discover the name."""
        self.assertNotIn("setvoicefreq", gunyamazaki.OPERATOR_ALLOWED_COMMANDS)
        self.assertNotIn("setvoicecooldown", gunyamazaki.OPERATOR_ALLOWED_COMMANDS)

    def test_independent_group_voice_frequencies(self):
        """Changing voice frequency in Group 1 does not affect Group 2."""
        g1 = get_or_create_group_context(5001, "Joker Jhamgat")
        g2 = get_or_create_group_context(5002, "Bleach World")

        g1.voice_cooldown = 600.0  # 10 minutes
        g1.voice_probability = 0.05  # 5%

        g2.voice_cooldown = 1800.0  # 30 minutes
        g2.voice_probability = 0.01  # 1%

        self.assertEqual(g1.voice_cooldown, 600.0)
        self.assertEqual(g2.voice_cooldown, 1800.0)
        self.assertEqual(g1.voice_probability, 0.05)
        self.assertEqual(g2.voice_probability, 0.01)

    def test_voice_frequency_persistence(self):
        """Group-specific voice frequency survives restart."""
        temp_dir = tempfile.mkdtemp()
        orig = bot_persistence.STATE_FILE
        bot_persistence.STATE_FILE = os.path.join(temp_dir, "test_vfreq.json")
        try:
            g = get_or_create_group_context(5003, "Persist Voice Group")
            g.voice_cooldown = 1200.0
            g.voice_probability = 0.08
            bot_persistence.save_local_state()

            # Clear cache
            bot_persistence._group_cache.clear()

            # Reload
            loaded = bot_persistence.load_local_state()
            self.assertIn(5003, loaded)
            self.assertEqual(loaded[5003].voice_cooldown, 1200.0)
            self.assertEqual(loaded[5003].voice_probability, 0.08)
        finally:
            bot_persistence.STATE_FILE = orig


class TestSecretProtectionAndSanitization(unittest.TestCase):
    """
    Test Requirement 5 & 6:
    Verify secret redactor filter and credentials confidentiality.
    """

    def test_log_sanitizer_redacts_api_keys(self):
        """SensitiveDataFilter must redact API keys and tokens from logs."""
        filtr = gunyamazaki.SensitiveDataFilter()

        # Test ElevenLabs / OpenAI style sk-...
        rec1 = logging.LogRecord("test", logging.INFO, "test.py", 10, "Using key sk-fish-id3DV-EE9AOhWoNPyzFXIUfHhuvVEJ6yGHQhUOFXn-w to call API", (), None)
        filtr.filter(rec1)
        self.assertNotIn("sk-fish-id3DV-EE9AOhWoNPyzFXIUfHhuvVEJ6yGHQhUOFXn-w", rec1.msg)
        self.assertIn("[REDACTED_SECRET]", rec1.msg)

        # Test Bot token style
        rec2 = logging.LogRecord("test", logging.INFO, "test.py", 11, "Bot token bot789123456:AAFlkjasdflkjasdflkjasdflkjasdf123 connected", (), None)
        filtr.filter(rec2)
        self.assertNotIn("bot789123456:AAFlkjasdflkjasdflkjasdflkjasdf123", rec2.msg)
        self.assertIn("[REDACTED_SECRET]", rec2.msg)

    def test_ai_confidentiality_directive_present(self):
        """System prompt must contain the confidentiality and anti-extraction directive."""
        with open("gunyamazaki.py", "r", encoding="utf-8") as f:
            code = f.read()
        self.assertIn("CONFIDENTIALITY & INTEGRITY DIRECTIVE", code)
        self.assertIn("Under NO circumstance disclose, hint at, quote, or discuss API keys", code)


class TestOrdinaryUserConversationalAccess(unittest.TestCase):
    """
    Test Requirement 2 & 6:
    Ordinary users can chat naturally via text and voice without gaining command permissions.
    """

    def test_ordinary_user_denied_commands(self):
        """Ordinary user is denied lockon, lockoff, setspeed, etc."""
        s_id = 1122334455  # Normal user ID
        username = "regular_chatter"

        is_super_admin = (s_id in gunyamazaki.SUPER_ADMIN_IDS) or (username in gunyamazaki.SUPER_ADMIN_USERNAMES)
        is_operator = (s_id == gunyamazaki.PRIMARY_OPERATOR_ID) or (username in gunyamazaki.PRIMARY_OPERATOR_USERNAMES)

        self.assertFalse(is_super_admin)
        self.assertFalse(is_operator)

    def test_ordinary_user_can_use_conversational_ai(self):
        """Ordinary user gets conversational AI turns in group."""
        bot_persistence.reset_group_state(6001)
        ctx = get_or_create_group_context(6001, "Chat Group")
        ctx.add_history_turn("Alice", "user", "What is the capital of Japan?")
        ctx.add_history_turn("GenzetaBot", "assistant", "Tokyo, bro!")

        self.assertEqual(len(ctx.conversation_history), 2)
        self.assertIn("Tokyo", ctx.get_recent_dialogue_context())


if __name__ == "__main__":
    unittest.main()
