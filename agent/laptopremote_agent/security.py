"""The certificate the viewer pins, the TLS side of the control channel and the shared secret."""
import hashlib
import hmac
import pathlib
import secrets
import ssl
import subprocess


class SecurityError(Exception):
    pass


def create_certificate(cert_path, key_path):
    """Makes a self-signed certificate and its key. The viewer pins the certificate, so its name
    and its end date mean nothing."""
    cert_path, key_path = pathlib.Path(cert_path), pathlib.Path(key_path)
    for path in (cert_path, key_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    key_path.touch(mode=0o600)  # owner-only before the key is written into it
    key_path.chmod(0o600)
    try:
        done = subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
             "-keyout", str(key_path), "-out", str(cert_path), "-days", "36500", "-subj", "/CN=laptopremote"],
            capture_output=True, text=True)
    except OSError as error:
        raise SecurityError(f"cannot run openssl: {error}") from None
    if done.returncode != 0:
        raise SecurityError(f"openssl could not make the certificate: {done.stderr.strip()}")
    key_path.chmod(0o600)


def fingerprint(cert_path):
    """Lowercase hex SHA-256 of the certificate, the value the viewer's config pins."""
    try:
        der = ssl.PEM_cert_to_DER_cert(pathlib.Path(cert_path).read_text())
    except (OSError, ValueError) as error:
        raise SecurityError(f"{cert_path}: {error}") from None
    return hashlib.sha256(der).hexdigest()


def server_context(cert_path, key_path):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2  # Windows 10 has no TLS 1.3
    try:
        context.load_cert_chain(cert_path, key_path)
    except (OSError, ssl.SSLError) as error:
        raise SecurityError(f"{cert_path} or {key_path}: {error}; run LaptopRemote.exe --setup on the PC") from None
    return context


def new_secret():
    return secrets.token_hex(32)


def same_secret(ours, theirs):
    if not ours or not theirs:
        return False
    return hmac.compare_digest(ours.encode(), theirs.encode())
