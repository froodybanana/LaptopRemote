import ipaddress
import pathlib
import tempfile
import unittest

from laptopremote_agent import config

GOOD = 'allowed_addresses = ["192.0.2.10"]\nsecret = "' + "s" * 64 + '"\n'


class ConfigTests(unittest.TestCase):
    def load(self, text):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "config.toml"
            path.write_text(text)
            return config.load(path)

    def test_load(self):
        loaded = self.load(GOOD + "bitrate_kbps = 12000\n")
        self.assertEqual(loaded.allowed_addresses, (ipaddress.ip_network("192.0.2.10/32"),))
        self.assertEqual(loaded.secret, "s" * 64)
        self.assertEqual(loaded.bitrate_kbps, 12000)
        self.assertEqual(loaded.control_port, 47800)
        self.assertEqual(loaded.video_send_port, 47802)
        self.assertEqual(loaded.panel, "eDP-1")

    def test_panel_name_must_be_a_plain_connector(self):
        # the name is written into Lua that Hyprland runs
        self.assertEqual(self.load(GOOD + 'panel = "DSI-1"\n').panel, "DSI-1")
        for bad in ("'eDP-1\"})'", '""', "7"):
            with self.assertRaises(config.ConfigError, msg=bad):
                self.load(GOOD + f"panel = {bad}\n")

    def test_missing_allowed_addresses(self):
        for line in ("", "allowed_addresses = []\n", 'allowed_address = "192.0.2.10"\n'):
            with self.assertRaises(config.ConfigError, msg=line):
                self.load(line + 'control_port = 1\nsecret = "' + "s" * 64 + '"\n')

    def test_allowed_addresses_are_addresses_or_networks(self):
        # compared with the address a connection comes from, so a host name would never match
        loaded = self.load('allowed_addresses = ["192.0.2.10", "10.0.0.0/24"]\nsecret = "' + "s" * 64 + '"\n')
        self.assertEqual(loaded.allowed_addresses,
                         (ipaddress.ip_network("192.0.2.10/32"), ipaddress.ip_network("10.0.0.0/24")))
        for bad in ('"192.0.2.10"', '["my-pc"]', '["10.0.0.1/24"]', '[5]', '[""]'):
            with self.assertRaises(config.ConfigError, msg=bad):
                self.load(f'allowed_addresses = {bad}\nsecret = "' + "s" * 64 + '"\n')

    def test_allows(self):
        loaded = config.Config(["192.0.2.10", "10.0.0.0/24"])
        self.assertTrue(loaded.allows("192.0.2.10"))
        self.assertTrue(loaded.allows("10.0.0.3"))
        self.assertFalse(loaded.allows("192.0.2.11"))
        self.assertFalse(loaded.allows("10.1.0.3"))
        self.assertFalse(loaded.allows("::1"))
        self.assertFalse(loaded.allows("my-pc"))

    def test_secret_is_required(self):
        short = "k" * 31
        for line in ("", f'secret = "{short}"\n', "secret = 12345678901234567890123456789012\n"):
            with self.assertRaises(config.ConfigError, msg=line) as caught:
                self.load('allowed_addresses = ["192.0.2.10"]\n' + line)
            self.assertNotIn(short, str(caught.exception))
            self.assertIn("--setup", str(caught.exception))

    def test_ports_and_bitrate_must_be_sane(self):
        for line in ("control_port = 0", "control_port = 70000", 'control_port = "x"', "control_port = true",
                     "video_send_port = 0", "bitrate_kbps = 10", "bitrate_kbps = 1.5"):
            with self.assertRaises(config.ConfigError, msg=line):
                self.load(GOOD + line + "\n")

    def test_keyboard_layout(self):
        loaded = self.load(GOOD)
        self.assertEqual((loaded.keyboard_layout, loaded.keyboard_variant, loaded.keyboard_options), ("us", "", ""))
        loaded = self.load(GOOD + 'keyboard_layout = "dk"\nkeyboard_variant = "nodeadkeys"\n'
                                  'keyboard_options = "compose:caps,shift:both_capslock_cancel"\n')
        self.assertEqual((loaded.keyboard_layout, loaded.keyboard_variant, loaded.keyboard_options),
                         ("dk", "nodeadkeys", "compose:caps,shift:both_capslock_cancel"))

    def test_keyboard_names_must_be_plain(self):
        for line in ('keyboard_layout = ""', 'keyboard_layout = "us;rm"', "keyboard_layout = 5",
                     'keyboard_variant = "a b"', "keyboard_variant = true", 'keyboard_options = "x\\ny"'):
            with self.assertRaises(config.ConfigError, msg=line):
                self.load(GOOD + line + "\n")

    def test_certificate_paths_expand_home(self):
        loaded = self.load(GOOD)
        self.assertTrue(loaded.certificate_path.is_absolute())
        self.assertTrue(str(loaded.certificate_path).endswith(".config/laptopremote/cert.pem"))
        self.assertTrue(str(loaded.private_key_path).endswith(".config/laptopremote/key.pem"))
        loaded = self.load(GOOD + 'certificate = "/tmp/c.pem"\nprivate_key = "/tmp/k.pem"\n')
        self.assertEqual(loaded.certificate_path, pathlib.Path("/tmp/c.pem"))
        self.assertEqual(loaded.private_key_path, pathlib.Path("/tmp/k.pem"))
        with self.assertRaises(config.ConfigError):
            self.load(GOOD + "certificate = 5\n")

    def test_encoder_defaults_to_vaapi_lowpower_444(self):
        loaded = self.load(GOOD)
        self.assertEqual(loaded.encoder, config.DEFAULT_ENCODER)
        self.assertIn("vah265lpenc name=enc", loaded.encoder)
        self.assertIn("format=VUYA", loaded.encoder)
        self.assertEqual(loaded.encoder_fragment(), config.DEFAULT_ENCODER.format(bitrate_kbps=20000))
        self.assertNotIn("{", loaded.encoder_fragment())

    def test_encoder_is_any_fragment_naming_enc(self):
        loaded = self.load(GOOD + 'bitrate_kbps = 8000\nencoder = "x264enc name=enc bitrate={bitrate_kbps} tune=zerolatency"\n')
        self.assertEqual(loaded.encoder_fragment(), "x264enc name=enc bitrate=8000 tune=zerolatency")
        for bad in ('"vah265lpenc"', '"vah265lpenc name=enc {rate}"', '"vah265lpenc name=enc {"', '""', "5"):
            with self.assertRaises(config.ConfigError, msg=bad) as caught:
                self.load(GOOD + f"encoder = {bad}\n")
            self.assertIn("encoder", str(caught.exception))

    def test_restore_keybind_is_plain(self):
        self.assertEqual(self.load(GOOD).restore_keybind, "SUPER + CTRL + SHIFT + Delete")
        self.assertEqual(self.load(GOOD + 'restore_keybind = "SUPER + F12"\n').restore_keybind, "SUPER + F12")
        for bad in ('""', '"SUPER + \\"x"', '"a;b"', "7"):
            with self.assertRaises(config.ConfigError, msg=bad):
                self.load(GOOD + f"restore_keybind = {bad}\n")
