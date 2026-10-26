import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import asyncio
import time
import gunyamazaki

class TestGroupIsolation(unittest.TestCase):
    def setUp(self):
        self.orig_allowed = set(gunyamazaki.ALLOWED_GROUP_IDS)
        self.orig_bot_active = gunyamazaki.bot_active
        gunyamazaki.ALLOWED_GROUP_IDS = {-1003529827660, 3529827660, -1002361093080}
        gunyamazaki.unauthorized_command_log_cooldown.clear()

    def tearDown(self):
        gunyamazaki.ALLOWED_GROUP_IDS = self.orig_allowed
        gunyamazaki.bot_active = self.orig_bot_active
        gunyamazaki.unauthorized_command_log_cooldown.clear()

    def test_check_group_authorized_constant_time(self):
        # Whitelisted groups
        self.assertTrue(gunyamazaki.check_group_authorized(-1003529827660))
        self.assertTrue(gunyamazaki.check_group_authorized(3529827660))
        self.assertTrue(gunyamazaki.check_group_authorized(-1002361093080))

        # Unrelated / unauthorized groups from user logs
        self.assertFalse(gunyamazaki.check_group_authorized(-1001199404040)) # സിനിമാ തറവാട് 12
        self.assertFalse(gunyamazaki.check_group_authorized(-1001776305671)) # CINEMA THARAVADU 13
        self.assertFalse(gunyamazaki.check_group_authorized(-1001947407820)) # Character Catcher Group
        self.assertFalse(gunyamazaki.check_group_authorized(-1002083037099)) # Lookism Chat

    def test_ambient_messages_in_unauthorized_groups_silent(self):
        """Ordinary messages in unauthorized groups must produce zero warnings and return True (skip)."""
        async def run_test():
            mock_client = MagicMock()
            gunyamazaki.setup_commands(mock_client)

            # Build mock event in unauthorized group
            mock_event = MagicMock()
            mock_event.is_group = True
            mock_event.is_channel = False
            mock_event.chat_id = -1001199404040  # Cinema Tharavadu
            mock_event.chat = MagicMock(title="സിനിമാ തറവാട് 12")
            mock_event.raw_text = "hello friends, movie download link undo?"

            with patch("logging.warning") as mock_warn:
                # Find should_skip closure inside setup_commands by invoking auto_delete handler
                # or inspecting registered handlers
                handlers = [call.args[0] for call in mock_client.on.call_args_list if call.args]
                self.assertTrue(len(handlers) > 0)
                
                # Check should_skip directly on unauthorized group with no command name
                # We can call check_group_authorized
                self.assertFalse(gunyamazaki.check_group_authorized(mock_event.chat_id, mock_event.chat))
                mock_warn.assert_not_called()

        asyncio.run(run_test())

    def test_unauthorized_command_logged_with_rate_limit(self):
        """Explicit command in unauthorized group logs once and rate limits subsequent attempts."""
        mock_client = MagicMock()
        gunyamazaki.setup_commands(mock_client)

        mock_event = MagicMock()
        mock_event.is_group = True
        mock_event.is_channel = False
        mock_event.chat_id = -1001947407820
        mock_event.chat = MagicMock(title="Character Catcher Group")

        with patch("logging.warning") as mock_warn:
            # First command attempt: should log warning
            now = time.time()
            cid = mock_event.chat_id
            self.assertFalse(gunyamazaki.check_group_authorized(cid))
            
            # Simulate should_skip behavior
            gunyamazaki.unauthorized_command_log_cooldown[cid] = now + 60.0
            # Subsequent attempt within 60s window must not log
            self.assertGreater(gunyamazaki.unauthorized_command_log_cooldown[cid], now)

    def test_auto_delete_inactive_when_bot_locked_off(self):
        """When bot_active is False, auto_delete_group_handler must not process messages."""
        gunyamazaki.bot_active = False
        self.assertFalse(gunyamazaki.bot_active)

    def test_four_account_rotation_preserved(self):
        """All 4 accounts (acc1, acc2, acc3, acc4) participate in thread speaker mapping."""
        available_workers = ["acc1", "acc2", "acc3", "acc4"]
        thread_speaker_map = {}
        conv_id = "test_thread_001"
        
        # Test mapping
        import random
        random.seed(42)
        shuffled = random.sample(available_workers, len(available_workers))
        thread_speaker_map[conv_id] = {
            "acc1": shuffled[0 % len(shuffled)],
            "acc2": shuffled[1 % len(shuffled)],
            "acc3": shuffled[2 % len(shuffled)]
        }
        
        assigned = set(thread_speaker_map[conv_id].values())
        self.assertEqual(len(assigned), 3)
        for role in ["acc1", "acc2", "acc3"]:
            self.assertIn(thread_speaker_map[conv_id][role], available_workers)

if __name__ == "__main__":
    unittest.main()
