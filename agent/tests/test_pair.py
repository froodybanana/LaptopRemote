import contextlib
import io
import os
import pathlib
import tempfile
import tomllib
import unittest

from laptopremote_agent import config, pair, security


class PairTests(unittest.TestCase):
    def test_with_secret_adds_a_first_line(self):
        text = '# my laptop\nallowed_addresses = ["192.0.2.10"]\npanel = "eDP-1"\n'
        result = pair.with_secret(text, "k" * 64)
        self.assertEqual(tomllib.loads(result),
                         {"allowed_addresses": ["192.0.2.10"], "panel": "eDP-1", "secret": "k" * 64})
        self.assertTrue(result.endswith(text))

    def test_with_secret_keeps_an_existing_one(self):
        text = 'allowed_addresses = ["192.0.2.10"]\nsecret = "' + "o" * 64 + '"\n'
        self.assertEqual(pair.with_secret(text, "k" * 64), text)

    def test_pair_creates_everything_once(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = pathlib.Path(folder)
            path, cert, key = folder / "config.toml", folder / "cert.pem", folder / "key.pem"
            path.write_text('allowed_addresses = ["192.0.2.10"]\n')
            path.chmod(0o644)
            first = pair.pair(path, cert, key)
            self.assertRegex(first["secret"], r"^[0-9a-f]{64}$")
            self.assertEqual(first["certificateSha256"], security.fingerprint(cert))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(config.load(path).secret, first["secret"])
            before = cert.read_bytes()
            self.assertEqual(pair.pair(path, cert, key), first)
            self.assertEqual(cert.read_bytes(), before)

    def test_pair_uses_the_paths_in_the_config(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = pathlib.Path(folder)
            path = folder / "config.toml"
            path.write_text(f'allowed_addresses = ["192.0.2.10"]\ncertificate = "{folder}/c.pem"\n'
                            f'private_key = "{folder}/k.pem"\n')
            result = pair.pair(path)
            self.assertEqual(result["certificateSha256"], security.fingerprint(folder / "c.pem"))
            self.assertTrue((folder / "k.pem").exists())

    def test_pair_without_config_is_a_config_error(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(config.ConfigError):
                pair.pair(pathlib.Path(folder) / "config.toml")

    def test_with_allowed_adds_an_address_on_the_same_line(self):
        text = '# laptop\nallowed_addresses = ["192.0.2.10"]  # the PC\npanel = "eDP-1"\n'
        result = pair.with_allowed(text, "10.0.0.3")
        self.assertEqual(tomllib.loads(result)["allowed_addresses"], ["192.0.2.10", "10.0.0.3"])
        self.assertIn("# the PC", result)
        self.assertTrue(result.endswith('panel = "eDP-1"\n'))

    def test_with_allowed_leaves_a_covered_address_alone(self):
        text = 'allowed_addresses = ["192.0.2.10", "10.0.0.0/24"]\n'
        self.assertEqual(pair.with_allowed(text, "10.0.0.3"), text)
        self.assertEqual(pair.with_allowed(text, "192.0.2.10"), text)

    def test_with_allowed_adds_the_key_when_missing(self):
        self.assertEqual(tomllib.loads(pair.with_allowed('panel = "eDP-1"\n', "192.0.2.10"))["allowed_addresses"],
                         ["192.0.2.10"])

    def test_with_allowed_refuses_what_it_cannot_rewrite(self):
        for text, address in (('allowed_addresses = [\n  "192.0.2.10",\n]\n', "10.0.0.3"),
                              ('allowed_addresses = ["192.0.2.10"]\n', "my-pc"),
                              ('allowed_addresses = ["192.0.2.10"]\n', "")):
            with self.assertRaises(config.ConfigError, msg=repr((text, address))):
                pair.with_allowed(text, address)

    def test_pair_with_allow_writes_the_address(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = pathlib.Path(folder)
            path, cert, key = folder / "config.toml", folder / "cert.pem", folder / "key.pem"
            path.write_text('allowed_addresses = ["192.0.2.10"]\n')
            pair.pair(path, cert, key, allow="192.0.2.11")
            self.assertTrue(config.load(path).allows("192.0.2.11"))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_client_address_comes_from_ssh_connection(self):
        self.assertEqual(pair.client_address({"SSH_CONNECTION": "192.0.2.10 51234 192.0.2.20 22"}), "192.0.2.10")
        self.assertIsNone(pair.client_address({}))
        self.assertIsNone(pair.client_address({"SSH_CONNECTION": ""}))

    def test_main_without_ssh_connection_is_a_usage_error(self):
        saved = os.environ.pop("SSH_CONNECTION", None)
        try:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(pair.main(["--allow-client"]), 2)
            self.assertIn("SSH_CONNECTION", err.getvalue())
        finally:
            if saved is not None:
                os.environ["SSH_CONNECTION"] = saved
