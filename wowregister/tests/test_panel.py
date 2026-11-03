import json
import threading
import unittest
from unittest.mock import Mock, patch
from urllib import request, error

from wowregister.panel import Controller, PanelServer
from wowregister.registration.windows import Desktop, PlaybackStopped, wait_for_start
from wowregister.registration.chain import run_cycle


class PanelTests(unittest.TestCase):
    def controller(self, runner=Mock()):
        with patch("wowregister.panel.device_id", return_value="a" * 64):
            controller = Controller(runner)
        self.addCleanup(controller.close)
        return controller

    def test_modes_and_rounds_forwarded_and_stop_is_cooperative(self):
        ready = threading.Event()
        def runner(mode, repeat, stop_event, **kwargs):
            self.assertEqual((mode, repeat), (2, 37))
            self.assertTrue(kwargs["allow_game_path_change"])
            kwargs["on_cycle"](1, repeat)
            ready.set()
            stop_event.wait(2)
            raise PlaybackStopped("已停止")
        controller = self.controller(runner)
        with patch("wowregister.panel.client.check_active"):
            controller.start(2, 37)
            self.assertTrue(ready.wait(1))
            with self.assertRaises(RuntimeError):
                controller.start(1, 1)
            controller.stop()
            controller.thread.join(2)
            self.assertEqual(controller.snapshot()["state"], "stopped")
            self.assertFalse(controller.thread.is_alive())

    def test_unlicensed_start_never_creates_worker(self):
        runner = Mock()
        controller = self.controller(runner)
        with patch("wowregister.panel.client.check_active", side_effect=RuntimeError("未激活")):
            with self.assertRaises(RuntimeError):
                controller.start(1, 1)
        runner.assert_not_called()
        self.assertIsNone(controller.thread)

    def test_cancel_while_waiting_for_f6_sends_no_input(self):
        desktop = Desktop.__new__(Desktop)
        desktop.stop_event = threading.Event()
        desktop.stop_event.set()
        desktop.down = Mock(return_value=False)
        with self.assertRaises(PlaybackStopped):
            wait_for_start(desktop, report=lambda _: None)
        self.assertEqual(desktop.down.call_count, 1)

    def test_license_expiry_checked_while_waiting_for_f6(self):
        desktop = Desktop.__new__(Desktop)
        desktop.stop_event = threading.Event()
        desktop.license_guard = Mock(side_effect=RuntimeError("已到期"))
        desktop.down = Mock(return_value=False)
        with self.assertRaisesRegex(RuntimeError, "已到期"):
            wait_for_start(desktop, report=lambda _: None)

    def test_engine_denies_license_before_loading_profiles_or_binding(self):
        with patch("wowregister.licensing.client.require_license", side_effect=RuntimeError("授权失败")), \
                patch("wowregister.registration.chain.load") as load, \
                patch("wowregister.registration.chain.Desktop") as desktop:
            with self.assertRaises(RuntimeError):
                run_cycle(1, 1)
        load.assert_not_called()
        desktop.assert_not_called()

    def test_local_http_requires_session_and_matching_origin(self):
        controller = self.controller()
        controller.start = Mock()
        server = PanelServer(controller)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with request.urlopen(server.origin, timeout=2) as response:
                page = response.read().decode()
            self.assertIn(server.token, page)
            self.assertNotIn("__SESSION_TOKEN__", page)
            payload = json.dumps({"mode": 2, "repeat": 10}).encode()
            for headers in ({}, {"Origin": "https://example.com", "X-Wowregister-Token": server.token}):
                req = request.Request(server.origin + "/api/start", data=payload,
                                      headers={"Content-Type": "application/json", **headers})
                with self.assertRaises(error.HTTPError) as caught:
                    request.urlopen(req, timeout=2)
                self.assertEqual(caught.exception.code, 403)
            controller.start.assert_not_called()
            req = request.Request(server.origin + "/api/start", data=payload,
                                  headers={"Content-Type": "application/json", "Origin": server.origin,
                                           "X-Wowregister-Token": server.token})
            with request.urlopen(req, timeout=2) as response:
                self.assertTrue(json.load(response)["ok"])
            controller.start.assert_called_once_with(2, 10)
        finally:
            server.shutdown()
            thread.join(2)
            server.server_close()


if __name__ == "__main__":
    unittest.main()
