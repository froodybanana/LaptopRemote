import hashlib
import pathlib
import socket
import ssl
import tempfile
import unittest

from laptopremote_agent import security


def handshake(server, client):
    """Drives both ends of a TLS handshake over non-blocking sockets in one thread."""
    pending = [server, client]
    for _ in range(100):
        for side in list(pending):
            try:
                side.do_handshake()
                pending.remove(side)
            except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
                pass
        if not pending:
            return
    raise AssertionError("handshake did not finish")


class SecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.folder.cleanup)
        cls.cert = pathlib.Path(cls.folder.name) / "cert.pem"
        cls.key = pathlib.Path(cls.folder.name) / "key.pem"
        security.create_certificate(cls.cert, cls.key)

    def test_certificate_serves_tls_and_matches_its_fingerprint(self):
        left, right = socket.socketpair()
        left.setblocking(False)
        right.setblocking(False)
        client_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        client_context.check_hostname = False
        client_context.verify_mode = ssl.CERT_NONE
        server = security.server_context(self.cert, self.key).wrap_socket(
            left, server_side=True, do_handshake_on_connect=False)
        client = client_context.wrap_socket(right, do_handshake_on_connect=False)
        self.addCleanup(server.close)
        self.addCleanup(client.close)
        handshake(server, client)
        self.assertEqual(hashlib.sha256(client.getpeercert(True)).hexdigest(), security.fingerprint(self.cert))
        self.assertRegex(security.fingerprint(self.cert), r"^[0-9a-f]{64}$")

    def test_private_key_is_for_the_owner_only(self):
        self.assertEqual(self.key.stat().st_mode & 0o777, 0o600)

    def test_tls_1_1_is_refused(self):
        self.assertEqual(security.server_context(self.cert, self.key).minimum_version, ssl.TLSVersion.TLSv1_2)

    def test_missing_certificate_is_a_security_error(self):
        missing = pathlib.Path(self.folder.name) / "nothing.pem"
        with self.assertRaises(security.SecurityError) as caught:
            security.server_context(missing, self.key)
        self.assertIn("nothing.pem", str(caught.exception))
        with self.assertRaises(security.SecurityError):
            security.fingerprint(missing)

    def test_secrets_differ_and_are_long(self):
        first, second = security.new_secret(), security.new_secret()
        self.assertNotEqual(first, second)
        self.assertRegex(first, r"^[0-9a-f]{64}$")

    def test_same_secret(self):
        self.assertTrue(security.same_secret("a" * 64, "a" * 64))
        self.assertFalse(security.same_secret("a" * 64, "b" * 64))
        self.assertFalse(security.same_secret("a" * 64, "a" * 63))
        self.assertFalse(security.same_secret("", ""))  # an agent without a secret answers nobody
        self.assertTrue(security.same_secret("søde" * 8, "søde" * 8))
