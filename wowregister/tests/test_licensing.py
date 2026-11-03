from datetime import datetime, timezone
import copy
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from license_server.legacy_verify import authorize, Denied, Unavailable, key_hash, handler
from wowregister.licensing import client
from wowregister.licensing.device import fingerprint, protect
from wowregister.tests.helpers import temporary_directory

CARD = "WA-" + "A" * 32
PEPPER = "test-only-pepper-" + "x" * 32
MACHINE_A, MACHINE_B = "a" * 64, "b" * 64


class LicensingTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"LICENSE_PEPPER": PEPPER})
        environment.start()
        self.addCleanup(environment.stop)
        self.record = {"schema_version": 1, "licenses": {
            key_hash(CARD, PEPPER): {"enabled": True, "expires_at": "2030-01-01T00:00:00Z", "device_id": MACHINE_A}}}

    def verify(self, machine=MACHINE_A, card=CARD, **kwargs):
        return authorize({"license_key": card, "device_id": machine}, read_record=lambda: self.record,
                         now=datetime(2026, 11, 3, tzinfo=timezone.utc), **kwargs)

    def test_only_prebound_machine_can_use_card(self):
        self.assertTrue(self.verify()["ok"])
        with self.assertRaises(Denied):
            self.verify(machine=MACHINE_B)
        with self.assertRaises(Denied):
            self.verify(card="WA-" + "B" * 32)

    def test_unbound_disabled_expired_or_malformed_expiry_fail_closed(self):
        original = copy.deepcopy(self.record)
        digest = key_hash(CARD, PEPPER)
        for field, value in [("device_id", None), ("enabled", False),
                             ("expires_at", "2026-01-01T00:00:00Z"), ("expires_at", "bad"),
                             ("expires_at", "2030-01-01")]:
            self.record = copy.deepcopy(original)
            self.record["licenses"][digest][field] = value
            with self.assertRaises(Denied):
                self.verify()

    def test_no_secret_or_bad_schema_is_unavailable(self):
        with patch.dict(os.environ, {"LICENSE_PEPPER": "short"}):
            with self.assertRaises(Unavailable):
                self.verify()
        self.record = {"licenses": {}}
        with self.assertRaises(Unavailable):
            self.verify()

    def test_storage_failure_never_authorizes(self):
        with self.assertRaises(Unavailable):
            authorize({"license_key": CARD, "device_id": MACHINE_A}, read_record=Mock(side_effect=Unavailable()))

    def test_missing_or_unicode_machine_binding_is_denied(self):
        for value in (None, "任意机器", "", MACHINE_A[:-1]):
            self.record["licenses"][key_hash(CARD, PEPPER)]["device_id"] = value
            with self.assertRaises(Denied):
                self.verify()

    def test_client_rejects_insecure_or_redirect_capable_url_config(self):
        for url in ["http://example.com/api/verify", "https://user:pass@example.com", "https://example.com?secret=x", ""]:
            with patch.dict(os.environ, {"WOWREGISTER_LICENSE_URL": url}), patch.object(Path, "exists", return_value=False):
                with self.assertRaises(RuntimeError):
                    client.service_url()

    def test_client_403_codes_show_specific_messages_without_upstream_details(self):
        messages = {
            "invalid_card": "卡密不存在或格式不正确，请核对卡密",
            "disabled": "该卡密已被停用，请联系管理员",
            "expired": "该卡密已到期，请联系管理员",
            "bound_to_other_device": "该卡密已在另一台电脑激活，不能在本机使用",
            "unknown_SECRET": "卡密验证未通过，请联系管理员核对状态",
        }
        for code, expected in messages.items():
            with self.subTest(code=code):
                body = io.BytesIO(json.dumps({"ok": False, "code": code, "message": "SECRET"}).encode())
                opener = Mock()
                opener.open.side_effect = HTTPError("https://example.com/api/verify", 403, "SECRET", {}, body)
                with patch.object(client.request, "build_opener", return_value=opener):
                    with self.assertRaises(RuntimeError) as raised:
                        client.verify("https://example.com/api/verify", CARD, MACHINE_A)
                self.assertEqual(str(raised.exception), expected)
                self.assertNotIn("SECRET", str(raised.exception))

    def test_client_accepts_automatic_activation_only_for_requested_machine(self):
        for machine in (MACHINE_A, MACHINE_B):
            with self.subTest(response_machine=machine):
                payload = {"ok": True, "device_id": machine, "activation": "activated", "recheck_after": 45}
                opener = Mock()
                opener.open.return_value = io.BytesIO(json.dumps(payload).encode())
                with patch.object(client.request, "build_opener", return_value=opener):
                    if machine == MACHINE_A:
                        self.assertIsNone(client.verify("https://example.com/api/verify", CARD, MACHINE_A))
                    else:
                        with self.assertRaisesRegex(RuntimeError, "授权响应无效"):
                            client.verify("https://example.com/api/verify", CARD, MACHINE_A)

    def test_machine_guid_normalized_and_raw_guid_not_uploaded(self):
        guid = "ABCDEF12-3456-7890-ABCD-EF1234567890"
        machine = fingerprint(guid)
        self.assertEqual(machine, fingerprint("{" + guid.lower() + "}"))
        self.assertEqual(len(machine), 64)
        self.assertNotIn(guid.lower(), machine)

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI only")
    def test_dpapi_round_trip_and_tampered_ciphertext_rejected(self):
        message = b"unit-test-only-no-real-card"
        encrypted = protect(message)
        self.assertNotIn(message, encrypted)
        self.assertEqual(protect(encrypted, decrypt=True), message)
        with self.assertRaises(RuntimeError):
            protect(b"invalid data", decrypt=True)

    def test_session_expiry_revocation_and_missing_activation_block_actions(self):
        session = client.Session("https://example.com/api/verify", CARD, MACHINE_A)
        session.check()
        session.failure = "revoked"
        with self.assertRaisesRegex(RuntimeError, "revoked"):
            session.check()
        session.failure, session.deadline = None, 0
        with self.assertRaises(RuntimeError):
            session.check()
        with patch.object(client, "_session", None):
            with self.assertRaises(RuntimeError):
                client.check_active()

    def test_cached_card_is_not_accepted_without_online_verification(self):
        with temporary_directory() as directory:
            path = Path(directory) / "license.dat"
            cached = dict(card=CARD, url="https://example.com/api/verify", device_id=MACHINE_A)
            path.write_bytes(b"encrypted")
            with patch.object(client, "CACHE", path), patch.object(client, "_session", None), \
                    patch.object(client, "protect", return_value=json.dumps(cached).encode()), \
                    patch.object(client, "service_url", return_value=cached["url"]), \
                    patch.object(client, "device_id", return_value=MACHINE_A), \
                    patch.object(client, "verify", side_effect=RuntimeError("revoked")):
                with self.assertRaisesRegex(RuntimeError, "revoked"):
                    client.require_license()
                self.assertIsNone(client._session)

    def test_http_handler_hides_upstream_secret_errors(self):
        instance = handler.__new__(handler)
        from email.message import Message
        instance.headers = Message()
        instance.headers["Content-Length"] = "2"
        instance.headers["Content-Type"] = "application/json"
        instance.rfile = io.BytesIO(b"{}")
        instance.reply = Mock()
        with patch("license_server.legacy_verify.authorize", side_effect=RuntimeError("SECRET")):
            instance.do_POST()
        self.assertEqual(instance.reply.call_args.args, (503, {"ok": False, "code": "temporarily_unavailable"}))

    def test_jsonbin_request_uses_application_user_agent(self):
        from license_server.legacy_verify import json_request
        opener = Mock()
        opener.open.return_value.__enter__ = Mock(return_value=Mock(read=Mock(return_value=b'{"ok":true}')))
        opener.open.return_value.__exit__ = Mock(return_value=False)
        with patch("license_server.legacy_verify.request.build_opener", return_value=opener):
            self.assertTrue(json_request("https://api.jsonbin.io/test", {})["ok"])
        req = opener.open.call_args.args[0]
        self.assertEqual(req.get_header("User-agent"), "Wowregister-License/0.3")

    def test_master_key_configuration_uses_master_header(self):
        with patch.dict(os.environ, {"JSONBIN_BIN_ID": "a"*24, "JSONBIN_MASTER_KEY": "test-master", "JSONBIN_ACCESS_KEY": ""}), \
                patch("license_server.legacy_verify.json_request", return_value=self.record) as read:
            self.assertTrue(authorize({"license_key": CARD, "device_id": MACHINE_A})["ok"])
        self.assertEqual(read.call_args.args[1]["X-Master-Key"], "test-master")


if __name__ == "__main__":
    unittest.main()
