"""Hyprland control over its command socket (what hyprctl does, without starting a process)."""
import json
import os
import socket


class HyprError(Exception):
    pass


def _socket_path():
    runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    folder = os.path.join(runtime, "hypr")
    signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") or max(
        os.listdir(folder), key=lambda name: os.path.getmtime(os.path.join(folder, name)))
    return os.path.join(folder, signature, ".socket.sock")


def command(text):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(_socket_path())
        sock.sendall((text if text.startswith("j/") else f"/{text}").encode())
        chunks = []
        while chunk := sock.recv(8192):
            chunks.append(chunk)
    return b"".join(chunks).decode(errors="replace")


def _expect_ok(text):
    reply = command(text)
    if reply.strip() != "ok":
        raise HyprError(f"{text}: {reply.strip()}")


def evaluate(lua):
    _expect_ok(f"eval {lua}")


def monitors():
    return json.loads(command("j/monitors all"))


def _monitor(name):
    return next((monitor for monitor in monitors() if monitor.get("name") == name), None)


def output_disabled(name):
    monitor = _monitor(name)
    return bool(monitor and monitor.get("disabled"))


def active_workspace(name):
    """The workspace an output is showing, or None if the output is unknown or disabled."""
    number = ((_monitor(name) or {}).get("activeWorkspace") or {}).get("id")
    return number if isinstance(number, int) and number > 0 else None


def disable_output(name):
    evaluate(f'hl.monitor({{output="{name}", disabled=true}})')


def enable_output(name):
    evaluate(f'hl.monitor({{output="{name}", disabled=false}})')


def focus_workspace(number):
    _expect_ok(f'dispatch hl.dsp.focus({{workspace="{number}"}})')


def wake():
    """Turns the displays back on if idling put them to sleep; a sleeping output is captured as black."""
    _expect_ok('dispatch hl.dsp.dpms({action="enable"})')


def output_exists(name):
    return f"Monitor {name} (" in command("monitors all")


def create_output(name):
    _expect_ok(f"output create headless {name}")


def remove_output(name):
    _expect_ok(f"output remove {name}")


def set_mode(name, width, height, scale):
    evaluate(f'hl.monitor({{output="{name}", mode="{width}x{height}@60", position="auto", scale={scale}}})')
