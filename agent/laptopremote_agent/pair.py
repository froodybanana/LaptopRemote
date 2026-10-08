"""Laptop side of pairing: python3 -m laptopremote_agent.pair [--allow-client]

Makes the certificate and the shared secret if they do not exist yet and prints, as JSON, the
two values the viewer's config needs. The viewer's setup dialog on the PC runs this over ssh.
With --allow-client the address the ssh client came from is added to allowed_addresses.
"""
import ipaddress
import json
import os
import re
import sys
import tomllib

from . import config as config_module
from . import security
from .config import ConfigError

_ALLOWED_LINE = re.compile(r"^(?P<head>allowed_addresses[ \t]*=[ \t]*\[)(?P<items>[^\]\n]*)(?P<tail>\].*)$",
                           re.MULTILINE)


def with_secret(text, secret):
    """The config text with a secret, as a new first line unless it already has one."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"config is not valid TOML: {error}") from None
    if "secret" in data:
        return text
    return f'secret = "{secret}"\n{text}'


def with_allowed(text, address):
    """The config text with `address` in allowed_addresses, unchanged when it is already allowed."""
    try:
        ipaddress.ip_address(address)
    except ValueError:
        raise ConfigError(f"{address!r} is not an IP address") from None
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"config is not valid TOML: {error}") from None
    current = data.get("allowed_addresses") or []
    if isinstance(current, list) and all(isinstance(item, str) for item in current):
        try:
            if config_module.Config(current).allows(address):
                return text
        except ValueError:
            pass  # a broken entry is reported by load() later
    if "allowed_addresses" not in data:
        return f'allowed_addresses = ["{address}"]\n{text}'
    by_hand = ConfigError("allowed_addresses must be on one line for pairing to add the PC's address; "
                          f'add "{address}" to it by hand')
    match = _ALLOWED_LINE.search(text)
    if match is None:
        raise by_hand
    items = match.group("items").rstrip()
    joined = f'{items}, "{address}"' if items.strip() else f'"{address}"'
    result = text[:match.start()] + match.group("head") + joined + match.group("tail") + text[match.end():]
    try:
        rewritten = tomllib.loads(result).get("allowed_addresses")
    except tomllib.TOMLDecodeError:
        raise by_hand from None
    if rewritten != list(current) + [address]:
        raise by_hand
    return result


def client_address(environ):
    """The address the ssh client connected from, or None when not under ssh."""
    parts = environ.get("SSH_CONNECTION", "").split()
    return parts[0] if parts else None


def pair(config_path=config_module.DEFAULT_PATH, cert_path=None, key_path=None, allow=None):
    try:
        text = config_path.read_text()
    except FileNotFoundError:
        raise ConfigError(f"{config_path} does not exist; create it with allowed_addresses = [\"<PC address>\"]") from None
    config_path.chmod(0o600)  # before the secret goes in
    changed = with_secret(text, security.new_secret())
    if allow:
        changed = with_allowed(changed, allow)
    if changed != text:
        config_path.write_text(changed)
    config = config_module.load(config_path)
    cert_path = cert_path or config.certificate_path
    key_path = key_path or config.private_key_path
    if not cert_path.exists() or not key_path.exists():
        security.create_certificate(cert_path, key_path)
    return {"secret": config.secret, "certificateSha256": security.fingerprint(cert_path)}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    allow = None
    if argv == ["--allow-client"]:
        allow = client_address(os.environ)
        if allow is None:
            print("--allow-client needs an ssh connection: SSH_CONNECTION is not set", file=sys.stderr)
            return 2
    elif argv:
        print("usage: python3 -m laptopremote_agent.pair [--allow-client]", file=sys.stderr)
        return 2
    try:
        print(json.dumps(pair(allow=allow)))
    except (ConfigError, security.SecurityError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
