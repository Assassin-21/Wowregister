import unittest
from unittest.mock import Mock
from PIL import Image, ImageDraw
from wowregister.tests.test_registration import fixture, FakeDesktop
from wowregister.registration.chain import enter_until, split_direct, validate_route, matches_checkpoint

class ChainTests(unittest.TestCase):
    def test_match_stops_enter(self):
        macro, image = fixture()
        desktop = FakeDesktop(image)
        desktop.press_enter = Mock()
        with self.assertRaisesRegex(RuntimeError, "尚未按回车"):
            enter_until(desktop, macro["actions"][3], 1)
        desktop.press_enter.assert_not_called()

    def test_match_after_enter_allows_return(self):
        macro, image = fixture()
        desktop = FakeDesktop(Image.new("RGB", image.size, "black"))
        def enter():
            desktop.image = image
        desktop.press_enter = Mock(side_effect=enter)
        enter_until(desktop, macro["actions"][3], 2)
        desktop.press_enter.assert_called_once()

    def test_timeout_bounds_enter(self):
        macro, image = fixture()
        desktop = FakeDesktop(Image.new("RGB", image.size, "black"))
        times = []
        desktop.press_enter = lambda: times.append(desktop.now())
        with self.assertRaises(RuntimeError):
            enter_until(desktop, macro["actions"][3], 2)
        self.assertGreater(len(times), 1)
        self.assertTrue(all(.5 <= b-a <= 1 for a,b in zip(times,times[1:])))

    def test_yellow_text_matches_across_background_changes(self):
        expected = Image.new("RGB", (100, 40), (20, 10, 5))
        actual = Image.new("RGB", (100, 40), (80, 70, 60))
        for image, offset in [(expected, 0), (actual, 1)]:
            draw = ImageDraw.Draw(image)
            for x in range(10, 80, 10):
                draw.rectangle((x+offset, 10, x+4+offset, 25), fill=(240, 220, 0))
        self.assertTrue(matches_checkpoint(expected, actual))
        self.assertFalse(matches_checkpoint(expected, Image.new("RGB", expected.size, (80,70,60))))
        self.assertFalse(matches_checkpoint(expected, Image.new("RGB", expected.size, (240,220,0))))

    def test_old_route_rejected(self):
        macro, _ = fixture()
        with self.assertRaises(ValueError):
            validate_route(macro, macro)
        direct = {**macro, "actions": macro["actions"][:2]+[macro["actions"][3]]}
        prefix, gate = split_direct(direct)
        self.assertEqual(len(prefix["actions"]), 2)
        self.assertEqual(gate["type"], "checkpoint")

class TimingTests(unittest.TestCase):
    def test_profile_delays_preserve_recordings(self):
        from wowregister.registration.macro import action_delay
        click = {"type": "click", "delay": 13.03}
        name = {"type": "name", "delay": .69}
        for _ in range(100):
            self.assertTrue(.8 <= action_delay(click, "direct") <= 1.2)
            self.assertTrue(13.03 <= action_delay(click, "ruleset") <= 13.53)
        self.assertEqual(action_delay(name, "direct"), .69)
        self.assertEqual(click["delay"], 13.03)

    def test_ruleset_first_and_last_click_use_short_wait(self):
        from wowregister.registration.macro import replay
        from unittest.mock import patch
        macro, image = fixture()
        click = macro["actions"][2]
        macro["actions"] = [{**click, "delay": value} for value in (4, 13, 8)]
        desktop = FakeDesktop(image)
        desktop.wait = Mock()
        with patch("wowregister.registration.macro.random.uniform", side_effect=[1.0, .7, .9]):
            replay(macro, desktop, timing="ruleset", report=lambda _: None)
        self.assertEqual([c.args[0] for c in desktop.wait.call_args_list], [1.0, .7, .9])

    def test_ruleset_eight_click_timing_ranges(self):
        from wowregister.registration.macro import replay
        from unittest.mock import patch
        macro, image = fixture()
        click = macro["actions"][2]
        macro["actions"] = [{**click, "delay": 5} for _ in range(8)]
        desktop = FakeDesktop(image)
        desktop.wait = Mock()
        with patch("wowregister.registration.macro.random.uniform", side_effect=lambda a,b: (a+b)/2):
            replay(macro, desktop, timing="ruleset", report=lambda _: None)
        self.assertEqual([c.args[0] for c in desktop.wait.call_args_list],
                         [1, 5.25, 5.25, 5.25, 5.25, .75, .75, 1])
