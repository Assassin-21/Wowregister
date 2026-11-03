import copy
import ctypes
import io
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

from wowregister.registration.macro import encode_image, image_error, load, replay, save, validate, validate_name
from wowregister.registration.windows import Desktop, Input
from wowregister.registration.record import record, main as record_main
from wowregister.registration.replay import main as replay_main
from wowregister.tests.helpers import temporary_directory


def fixture():
    image = Image.new("RGB", (100, 40), "black")
    ImageDraw.Draw(image).rectangle((10, 8, 85, 25), fill="white")
    macro = dict(version=2, executable="C:/Game/Wow.exe", client_size=[800, 600], names=["测试角色", "第二段"],
                 actions=[dict(type="name", slot=0, delay=0), dict(type="name", slot=1, delay=.1),
                          dict(type="click", delay=.2, x=200, y=300, button="left", hold=.05),
                          dict(type="checkpoint", delay=.2, box=[200, 200, 300, 240], image=encode_image(image)),
                          dict(type="click", delay=.2, x=250, y=350, button="left", hold=.05)])
    return macro, image


class FakeDesktop:
    def __init__(self, image):
        self.image, self.clock, self.sent, self.captures = image, 0, [], 0
        self.stopped = False

    def now(self):
        return self.clock

    def guard(self):
        if self.stopped:
            raise RuntimeError("stopped")

    def wait(self, duration):
        self.guard()
        self.clock += duration

    def type_name(self, name):
        self.guard()
        self.sent.append(("name", name))

    def click(self, action):
        self.guard()
        self.sent.append(("click", action["y"]))

    def capture(self, box):
        self.captures += 1
        return self.image


class RegistrationTests(unittest.TestCase):
    def test_round_trip_and_unicode(self):
        macro, _ = fixture()
        with temporary_directory() as directory:
            path = Path(directory) / "macro.json"
            save(path, macro)
            self.assertEqual(load(path), macro)

    def test_replays_exactly_bounded_rounds_and_two_matches_per_gate(self):
        macro, image = fixture()
        desktop = FakeDesktop(image)
        replay(macro, desktop, repeat=3, report=lambda _: None)
        self.assertEqual(len(desktop.sent), 12)
        self.assertEqual(desktop.sent[:2], [("name", "测试角色"), ("name", "第二段")])
        self.assertEqual(desktop.captures, 6)
        self.assertGreaterEqual(desktop.clock, 10)

    def test_success_or_changed_screen_stops_before_closing_dialog(self):
        macro, _ = fixture()
        desktop = FakeDesktop(Image.new("RGB", (100, 40), "black"))
        with self.assertRaisesRegex(RuntimeError, "未看到"):
            replay(macro, desktop, repeat=30, timeout=1, report=lambda _: None)
        self.assertEqual(desktop.sent, [("name", "测试角色"), ("name", "第二段"), ("click", 300)])

    def test_transient_match_is_not_enough(self):
        macro, image = fixture()
        desktop = FakeDesktop(image)
        def capture(box):
            desktop.captures += 1
            return image if desktop.captures % 2 else Image.new("RGB", image.size, "black")
        desktop.capture = capture
        with self.assertRaises(RuntimeError):
            replay(macro, desktop, timeout=1, report=lambda _: None)
        self.assertEqual(len(desktop.sent), 3)

    def test_focus_loss_after_capture_prevents_next_input(self):
        macro, image = fixture()
        desktop = FakeDesktop(image)
        def capture(box):
            desktop.stopped = True
            return image
        desktop.capture = capture
        with self.assertRaisesRegex(RuntimeError, "stopped"):
            replay(macro, desktop, report=lambda _: None)
        self.assertEqual(len(desktop.sent), 3)

    def test_repeat_without_late_checkpoint_rejected_before_input(self):
        macro, image = fixture()
        for actions in ([a for a in macro["actions"] if a["type"] != "checkpoint"],
                        [macro["actions"][3], macro["actions"][0]]):
            bad = {**macro, "actions": actions}
            desktop = FakeDesktop(image)
            with self.assertRaises(ValueError):
                replay(bad, desktop, repeat=2)
            self.assertEqual(desktop.sent, [])

    def test_invalid_files_and_parameters_fail_before_input(self):
        macro, image = fixture()
        for field, value in [("delay", float("nan")), ("x", 800), ("hold", 8), ("button", "middle")]:
            bad = copy.deepcopy(macro)
            bad["actions"][2][field] = value
            with self.assertRaises(ValueError):
                validate(bad)
        bad = copy.deepcopy(macro)
        bad["actions"][3]["image"] = "invalid"
        with self.assertRaises(ValueError):
            validate(bad)
        for options in (dict(repeat=0), dict(interval=0), dict(timeout=float("inf")), dict(tolerance=float("nan"))):
            desktop = FakeDesktop(image)
            with self.assertRaises(ValueError):
                replay(macro, desktop, **options)
            self.assertEqual(desktop.sent, [])

    def test_ready_gate_timeout_blocks_following_click(self):
        macro, image = fixture()
        gate = {**macro["actions"][3], "purpose": "ready", "delay": 0}
        macro["actions"] = [gate, macro["actions"][2]]
        desktop = FakeDesktop(Image.new("RGB", image.size, "black"))
        with self.assertRaises(RuntimeError):
            replay(macro, desktop, timeout=1, report=lambda _: None)
        self.assertEqual(desktop.sent, [])
        with self.assertRaises(ValueError):
            replay(macro, FakeDesktop(image), repeat=2)
        desktop = FakeDesktop(image)
        replay(macro, desktop, report=lambda _: None)
        self.assertEqual(desktop.sent, [("click", 300)])

    def test_blank_checkpoint_is_rejected(self):
        macro, _ = fixture()
        macro["actions"][3]["image"] = encode_image(Image.new("RGB", (100, 40), "black"))
        with self.assertRaisesRegex(ValueError, "过于单一"):
            validate(macro)

    def test_changed_text_pixels_are_counted(self):
        original = Image.new("RGB", (100, 40), "black")
        changed = original.copy()
        ImageDraw.Draw(changed).rectangle((0, 0, 9, 19), fill=(80, 80, 80))
        self.assertAlmostEqual(image_error(original, changed), .05)

    def test_click_releases_mouse_when_stop_happens_during_hold(self):
        desktop = Desktop.__new__(Desktop)
        desktop.guard = Mock()
        desktop.ensure_modifiers_released = Mock()
        desktop.move_to = Mock()
        desktop.geometry = Mock(return_value=(0, 0, 800, 600))
        desktop.user = Mock()
        desktop.wait = Mock(side_effect=RuntimeError("F10"))
        events = []
        desktop.send = lambda event: events.append(event.mi.flags)
        with self.assertRaisesRegex(RuntimeError, "F10"):
            desktop.click(fixture()[0]["actions"][2])
        self.assertEqual(events, [2, 4])

    def test_unicode_text_releases_keys_and_never_uses_clipboard(self):
        desktop = Desktop.__new__(Desktop)
        desktop.guard = Mock()
        desktop.ensure_modifiers_released = Mock()
        desktop.move_to = Mock()
        desktop.wait = Mock()
        desktop.key = Mock()
        desktop.type_name("中A")
        calls = desktop.key.call_args_list
        self.assertTrue(any(call.kwargs == {"scan": ord("中"), "flags": 4} for call in calls))
        self.assertTrue(any(call.kwargs == {"scan": ord("中"), "flags": 6} for call in calls))

    def test_win32_input_layout_matches_platform(self):
        self.assertEqual(ctypes.sizeof(Input), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)

    def test_recorder_keeps_click_name_and_failure_gate_in_order(self):
        _, image = fixture()
        desktop = FakeDesktop(image)
        desktop.executable = "C:/Game/Wow.exe"
        desktop.initial_geometry = (0, 0, 800, 600)
        desktop.dpi = 96
        desktop.bind = Mock()
        desktop.position = Mock(return_value=(250, 220))
        frames = [{0x75}, set(), {1}, set(), {0x76}, set(), {0x77}, set(), {0x78}, set(), {0x75}]
        frame = [0]
        desktop.down = lambda key: key in frames[frame[0]]
        desktop.now = lambda: frame[0] * .1
        def advance(_):
            frame[0] += 1
        with patch("wowregister.registration.record.time.sleep", side_effect=advance), patch("sys.stdout", new_callable=io.StringIO):
            macro = record(desktop, ["中文名", "Second"], (100, 40))
        self.assertEqual([a["type"] for a in macro["actions"]], ["click", "name", "name", "checkpoint"])
        self.assertEqual(desktop.sent, [("name", "中文名"), ("name", "Second")])
        self.assertEqual([a["slot"] for a in macro["actions"] if a["type"] == "name"], [0, 1])
        self.assertAlmostEqual(macro["actions"][0]["hold"], .1)
        validate(macro)

    def test_release_click_and_name_hotkey_in_same_poll(self):
        _, image = fixture()
        desktop = FakeDesktop(image)
        desktop.executable = "C:/Game/Wow.exe"
        desktop.initial_geometry = (0, 0, 800, 600)
        desktop.dpi = 96
        desktop.bind = Mock()
        desktop.position = Mock(return_value=(250, 220))
        frames = [set(), {1}, {0x76}, set(), {0x77}, set(), {0x75}]
        frame = [0]
        desktop.down = lambda key: key in frames[frame[0]]
        desktop.now = lambda: frame[0] * .1
        def advance(_):
            frame[0] += 1
        with patch("wowregister.registration.record.time.sleep", side_effect=advance), patch("sys.stdout", new_callable=io.StringIO):
            macro = record(desktop, ["First", "Second"])
        self.assertEqual([a["type"] for a in macro["actions"]], ["click", "name", "name"])
        self.assertEqual(desktop.sent, [("name", "First"), ("name", "Second")])

    def test_cancelled_recording_does_not_overwrite_existing_file(self):
        with temporary_directory() as directory:
            path = Path(directory) / "macro.json"
            path.write_text("keep original", encoding="utf-8")
            with patch("sys.argv", ["record", "--output", str(path), "--name-first", "角色名", "--name-second", "Second"]), \
                    patch("wowregister.registration.record.Desktop"), \
                    patch("wowregister.registration.record.wait_for_start"), \
                    patch("wowregister.registration.record.record", side_effect=RuntimeError("F10")), \
                    patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(record_main(), 1)
            self.assertEqual(path.read_text(encoding="utf-8"), "keep original")

    def test_inspect_cli_does_not_initialize_desktop(self):
        macro, _ = fixture()
        with temporary_directory() as directory:
            path = Path(directory) / "macro.json"
            save(path, macro)
            with patch("sys.argv", ["replay", "--macro", str(path), "--inspect"]), \
                    patch("wowregister.registration.replay.Desktop") as adapter, \
                    patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(replay_main(), 0)
            adapter.assert_not_called()

    def test_name_limits_apply_to_each_field(self):
        for good in ["一二三四五六", "abcdefghijkl", "中文AbCdEfGh", "A"]:
            self.assertEqual(validate_name(good), good)
        for bad in ["一二三四五六七", "abcdefghijklm", "中文AbCdEfGhI", "名字1", "名字!", "", "A B", "é"]:
            with self.assertRaises(ValueError, msg=bad):
                validate_name(bad)
        macro, _ = fixture()
        macro["names"][1] = "一二三四五六七"
        with self.assertRaises(ValueError):
            validate(macro)

    def test_record_and_replay_work_without_license_verification(self):
        macro, _ = fixture()
        with temporary_directory() as directory:
            path = Path(directory) / "macro.json"
            with patch("wowregister.licensing.client.require_license", side_effect=AssertionError("licensing must stay disabled")) as authorization, \
                    patch("sys.stdout", new_callable=io.StringIO):
                with patch("sys.argv", ["record", "--output", str(path), "--name-first", "First", "--name-second", "Second"]), \
                        patch("wowregister.registration.record.Desktop"), \
                        patch("wowregister.registration.record.wait_for_start"), \
                        patch("wowregister.registration.record.record", return_value=macro) as recorder:
                    self.assertEqual(record_main(), 0)
                    recorder.assert_called_once()
                self.assertEqual(load(path), macro)
                with patch("sys.argv", ["replay", "--macro", str(path)]), \
                        patch("wowregister.registration.replay.Desktop"), \
                        patch("wowregister.registration.replay.wait_for_start"), \
                        patch("wowregister.registration.replay.replay") as player:
                    self.assertEqual(replay_main(), 0)
                    player.assert_called_once()
                authorization.assert_not_called()


if __name__ == "__main__":
    unittest.main()
