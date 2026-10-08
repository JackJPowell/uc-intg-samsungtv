"""Setup authorization regression tests.

:copyright: (c) 2026 by Jack Powell
:license: MPL-2.0, see LICENSE for details.
"""

import importlib.util
import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from ucapi import DriverSetupRequest, RequestUserInput, SetupError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "intg-samsungtv"))
from const import SamsungConfig

spec = importlib.util.spec_from_file_location(
    "samsung_setup", Path(__file__).resolve().parents[1] / "intg-samsungtv/setup.py"
)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def tv(identifier="tv", **kwargs):
    """Create a minimal TV configuration."""
    return SamsungConfig(identifier, identifier, "local", "192.0.2.1", **kwargs)


def response(status, data=None):
    """Mock an aiohttp response context manager."""
    result = MagicMock()
    result.status = status
    result.json = AsyncMock(return_value=data or {})
    result.__aenter__ = AsyncMock(return_value=result)
    result.__aexit__ = AsyncMock(return_value=False)
    return result


class SetupTests(unittest.IsolatedAsyncioTestCase):
    """Exercise choices, credential reuse, and validation failures."""

    def setUp(self):
        self.existing = tv(
            smartthings_access_token="access",
            smartthings_refresh_token="refresh",
            smartthings_worker_url="https://assigned.example",
        )
        self.config = MagicMock()
        self.devices = [self.existing]
        self.config.all.side_effect = lambda: iter(self.devices)
        self.flow = setup.SamsungSetupFlow(self.config, driver=MagicMock())
        self.flow._get_oauth_auth_screen = AsyncMock(
            return_value=RequestUserInput({"en": "OAuth"}, [])
        )

    async def test_unchecked_never_reuses_or_prompts(self):
        self.flow._validate_smartthings_tokens = AsyncMock()
        for value in (False, "false", None):
            target = tv("new")
            self.assertIsNone(
                await self.flow.get_additional_configuration_screen(
                    target, {"enable_smartthings": value}
                )
            )
            self.assertIsNone(target.smartthings_access_token)
        self.flow._validate_smartthings_tokens.assert_not_awaited()
        self.flow._get_oauth_auth_screen.assert_not_awaited()

    async def test_checked_reuses_existing_for_add_and_update(self):
        self.flow._validate_smartthings_tokens = AsyncMock(return_value=True)
        for identifier in ("new", "tv"):
            target = tv(identifier)
            self.assertIsNone(
                await self.flow.get_additional_configuration_screen(
                    target, {"enable_smartthings": "true"}
                )
            )
            self.assertEqual(target.smartthings_access_token, "access")
            self.assertEqual(target.smartthings_worker_url, "https://assigned.example")
        self.flow._get_oauth_auth_screen.assert_not_awaited()

    async def test_checked_without_tokens_goes_directly_to_oauth(self):
        self.devices.clear()
        result = await self.flow.get_additional_configuration_screen(
            tv(), {"enable_smartthings": True}
        )
        self.assertIsInstance(result, RequestUserInput)
        self.flow._get_oauth_auth_screen.assert_awaited_once()

    async def test_invalid_tokens_go_to_oauth(self):
        self.flow._validate_smartthings_tokens = AsyncMock(return_value=False)
        await self.flow.get_additional_configuration_screen(
            tv(), {"enable_smartthings": True}
        )
        self.flow._get_oauth_auth_screen.assert_awaited_once()

    async def test_unverifiable_tokens_do_not_register_again(self):
        self.flow._validate_smartthings_tokens = AsyncMock(return_value=None)
        result = await self.flow.get_additional_configuration_screen(
            tv(), {"enable_smartthings": True}
        )
        self.assertIsInstance(result, SetupError)
        self.flow._get_oauth_auth_screen.assert_not_awaited()

    async def test_fresh_setup_clears_tokens(self):
        self.config.clear.side_effect = self.devices.clear
        self.flow._build_restore_prompt_screen = AsyncMock(
            return_value=RequestUserInput({"en": "Restore"}, [])
        )
        await self.flow.handle_driver_setup(DriverSetupRequest(False, {}))
        self.assertEqual(self.devices, [])
        self.flow._validate_smartthings_tokens = AsyncMock(return_value=True)
        target = tv()
        await self.flow.get_additional_configuration_screen(
            target, {"enable_smartthings": True}
        )
        self.assertIsNone(target.smartthings_access_token)
        self.flow._validate_smartthings_tokens.assert_not_awaited()
        self.flow._get_oauth_auth_screen.assert_awaited_once()

    async def test_reset_clears_previously_reused_tokens(self):
        self.config.clear.side_effect = self.devices.clear
        screen = RequestUserInput({"en": "Setup"}, [])
        self.flow._build_configuration_mode_screen = AsyncMock(return_value=screen)
        self.flow._build_restore_prompt_screen = AsyncMock(return_value=screen)
        await self.flow.handle_driver_setup(DriverSetupRequest(True, {}))
        self.flow._validate_smartthings_tokens = AsyncMock(return_value=True)
        before_reset = tv("new")
        await self.flow.get_additional_configuration_screen(
            before_reset, {"enable_smartthings": True}
        )
        self.assertEqual(before_reset.smartthings_access_token, "access")
        await self.flow._handle_configuration_mode(
            SimpleNamespace(input_values={"action": "reset"})
        )
        self.assertEqual(self.devices, [])
        self.flow._validate_smartthings_tokens.reset_mock()
        target = tv()
        await self.flow.get_additional_configuration_screen(
            target, {"enable_smartthings": True}
        )
        self.assertIsNone(target.smartthings_access_token)
        self.flow._validate_smartthings_tokens.assert_not_awaited()
        self.flow._get_oauth_auth_screen.assert_awaited_once()

    async def test_reconfigure_keeps_tokens_for_reuse(self):
        self.flow._build_configuration_mode_screen = AsyncMock(
            return_value=RequestUserInput({"en": "Setup"}, [])
        )
        await self.flow.handle_driver_setup(DriverSetupRequest(True, {}))
        self.config.clear.assert_not_called()
        self.flow._validate_smartthings_tokens = AsyncMock(return_value=True)
        target = tv()
        await self.flow.get_additional_configuration_screen(
            target, {"enable_smartthings": True}
        )
        self.assertEqual(target.smartthings_access_token, "access")
        self.flow._get_oauth_auth_screen.assert_not_awaited()

    async def test_discovery_selection_honors_checked_and_unchecked(self):
        self.flow._validate_smartthings_tokens = AsyncMock(return_value=True)
        discovered = SimpleNamespace(address="192.0.2.1")
        for enabled in (False, "false", True, "true"):
            values = await self.flow.prepare_input_from_discovery(
                discovered, {"enable_smartthings": enabled}
            )
            target = tv("new")
            self.assertIsNone(
                await self.flow.get_additional_configuration_screen(target, values)
            )
            self.assertEqual(
                target.smartthings_access_token,
                "access" if str(enabled).lower() == "true" else None,
            )

    async def test_another_valid_grant_is_tried_before_authorization(self):
        self.devices.append(
            replace(
                self.existing, identifier="second", smartthings_access_token="valid"
            )
        )
        self.flow._validate_smartthings_tokens = AsyncMock(side_effect=[False, True])
        target = tv("new")
        await self.flow.get_additional_configuration_screen(
            target, {"enable_smartthings": True}
        )
        self.assertEqual(target.smartthings_access_token, "valid")
        self.flow._get_oauth_auth_screen.assert_not_awaited()

    async def test_valid_access_token_requires_no_refresh(self):
        session = MagicMock()
        session.get.return_value = response(200)
        with self.mock_session(session):
            self.assertTrue(await self.flow._validate_smartthings_tokens(self.existing))
        session.post.assert_not_called()

    async def test_capacity_error_shows_contact_message(self):
        session = MagicMock()
        session.get.return_value = response(
            503, {"error": "All sub-workers are at capacity"}
        )
        with self.mock_session(session):
            screen = await setup.SamsungSetupFlow._get_oauth_auth_screen(self.flow)
        self.assertIsInstance(screen, RequestUserInput)
        message = screen.settings[0]["field"]["label"]["value"]["en"]
        self.assertIn("slots are currently full", message)
        self.assertIn("contact Jack Powell", message)
        self.assertIn("/issues/new?", message)
        self.assertEqual(screen.settings[1]["field"]["dropdown"]["value"], "continue")

    async def test_other_worker_error_does_not_claim_slots_are_full(self):
        session = MagicMock()
        session.get.return_value = response(503, {"error": "No sub-workers configured"})
        with self.mock_session(session):
            screen = await setup.SamsungSetupFlow._get_oauth_auth_screen(self.flow)
        self.assertIsInstance(screen, RequestUserInput)
        message = screen.settings[0]["field"]["label"]["value"]["en"]
        self.assertIn("currently unavailable", message)
        self.assertNotIn("slots are currently full", message)

    async def test_continue_without_smartthings_completes_setup(self):
        target = tv("new")
        self.flow._pending_device_config = target
        self.flow._await_setup_completion = AsyncMock()
        msg = SimpleNamespace(input_values={"smartthings_setup_action": "continue"})
        await self.flow._handle_additional_configuration_response(msg)
        self.config.add_or_update.assert_called_once_with(target)
        self.assertIsNone(target.smartthings_access_token)
        self.assertIsNone(self.flow._pending_device_config)
        self.flow._get_oauth_auth_screen.assert_not_awaited()

    async def test_retry_smartthings_returns_authorization_screen(self):
        msg = SimpleNamespace(input_values={"smartthings_setup_action": "retry"})
        screen = await self.flow.handle_additional_configuration_response(msg)
        self.assertIsInstance(screen, RequestUserInput)
        self.flow._get_oauth_auth_screen.assert_awaited_once()

    def mock_session(self, session):
        """Replace the HTTP session while retaining real request behavior."""
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        return patch.object(setup.aiohttp, "ClientSession", return_value=session)

    async def test_refresh_rotates_and_persists_shared_credentials(self):
        other = replace(self.existing, identifier="other")
        self.devices.append(other)
        session = MagicMock()
        session.get.return_value = response(401)
        session.post.return_value = response(
            200,
            {
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 3600,
            },
        )
        with (
            self.mock_session(session),
            patch.object(setup.time, "time", return_value=1000),
        ):
            self.assertTrue(await self.flow._validate_smartthings_tokens(self.existing))
        session.post.assert_called_once_with(
            "https://assigned.example/refresh", json={"refresh_token": "refresh"}
        )
        for device in self.devices:
            self.assertEqual(device.smartthings_access_token, "new-access")
            self.assertEqual(device.smartthings_refresh_token, "new-refresh")
            self.assertEqual(device.smartthings_token_expires, 4600)
        self.assertEqual(self.config.update.call_count, 2)

    async def test_rejected_refresh_requires_new_authorization(self):
        session = MagicMock()
        session.get.return_value = response(401)
        session.post.return_value = response(
            400,
            {"error": "Token refresh failed", "details": '{"error":"invalid_grant"}'},
        )
        with self.mock_session(session):
            self.assertFalse(
                await self.flow._validate_smartthings_tokens(self.existing)
            )

    async def test_api_failure_preserves_credentials(self):
        session = MagicMock()
        session.get.return_value = response(503)
        with self.mock_session(session):
            self.assertIsNone(
                await self.flow._validate_smartthings_tokens(self.existing)
            )
        session.post.assert_not_called()
        self.assertEqual(self.existing.smartthings_access_token, "access")

    async def test_timeout_does_not_require_new_authorization(self):
        session = MagicMock()
        session.get.side_effect = TimeoutError
        with self.mock_session(session):
            self.assertIsNone(
                await self.flow._validate_smartthings_tokens(self.existing)
            )

    async def test_refresh_without_rotation_keeps_refresh_token(self):
        session = MagicMock()
        session.get.return_value = response(401)
        session.post.return_value = response(200, {"access_token": "renewed"})
        with self.mock_session(session):
            self.assertTrue(await self.flow._validate_smartthings_tokens(self.existing))
        self.assertEqual(self.existing.smartthings_refresh_token, "refresh")

    async def test_oauth_submission_applies_tokens_and_expiration(self):
        self.flow._pending_device_config = tv()
        msg = SimpleNamespace(
            input_values={
                "tokens_json": json.dumps(
                    {
                        "access_token": "new",
                        "refresh_token": "new-refresh",
                        "expires_in": 100,
                    }
                )
            }
        )
        with patch.object(setup.time, "time", return_value=1000):
            self.assertIsNone(
                await self.flow.handle_additional_configuration_response(msg)
            )
        self.assertEqual(
            self.flow._pending_device_config.smartthings_token_expires, 1100
        )

    def test_first_screen_labels(self):
        for fields in (
            self.flow.get_manual_entry_form().settings,
            self.flow.get_additional_discovery_fields(),
        ):
            checkbox = next(
                field for field in fields if field["id"] == "enable_smartthings"
            )
            self.assertEqual(checkbox["label"]["en"], "Enable SmartThings")


if __name__ == "__main__":
    unittest.main()
