#!/usr/bin/env python3
"""MIDI probe for the M-VAVE / Cuvave Cube Baby.

The pedal speaks USB-MIDI, but only its proprietary SysEx protocol is
documented. Nobody has published whether it also reacts to standard channel
messages (Program Change / Control Change) like its siblings do (Tank Mini:
PC switches presets; Blackbox: PC presets + CC toggles). This probe sends
those messages so you can watch the pedal and note what it accepts.

Transport: python-rtmidi if installed (pip install rtmidi), otherwise the
`amidi` command from alsa-utils (Linux).

Usage:
    python3 tools/midi_probe.py --list          # list MIDI ports
    python3 tools/midi_probe.py --port hw:2 --identify   # SysEx handshake test
    python3 tools/midi_probe.py --port hw:2 --pc         # cycle Program Changes
    python3 tools/midi_probe.py --port hw:2 --cc         # sweep common CCs
    python3 tools/midi_probe.py --port hw:2 --live       # step through edits

Watch the pedal while it runs: preset LED changes, sound changes, anything.
Nothing sent here writes to flash; the SysEx live-edit test only touches the
edit buffer (RAM, lost at power-off).
"""

import argparse
import sys
import time

# ---------------------------------------------------------------------------
# SysEx framing (documented in docs/cube-baby-modding.md, from cubebaby-editor
# PROTOCOL.md): F0 <7-bit packed payload> F7, payload = 00 59 | CMD | LEN u24
# LE | DATA | CHK, CHK = ~sum(DATA) & 0xFF.
# ---------------------------------------------------------------------------

MAGIC = b"\x00\x59"


def pack7(data: bytes) -> bytes:
    out, acc, n = bytearray(), 0, 0
    for b in data:
        acc |= b << n
        n += 8
        while n >= 7:
            out.append(acc & 0x7F)
            acc >>= 7
            n -= 7
    if n:
        out.append(acc & 0x7F)
    return bytes(out)


def frame(cmd: int, data: bytes = b"") -> bytes:
    payload = MAGIC + bytes([cmd]) + len(data).to_bytes(3, "little") + data
    chk = (~sum(data)) & 0xFF
    payload += bytes([chk])
    return b"\xF0" + pack7(payload) + b"\xF7"


def unpack7(packed: bytes) -> bytes:
    acc, n, out = 0, 0, bytearray()
    for b in packed:
        acc |= b << n
        n += 7
        while n >= 8:
            out.append(acc & 0xFF)
            acc >>= 8
            n -= 8
    if n and acc:
        out.append(acc & 0xFF)
    return bytes(out)


def parse_sysex(msg: bytes):
    """Return (cmd, data) if the message looks like a pedal reply, else None."""
    if len(msg) < 4 or msg[0] != 0xF0 or msg[-1] != 0xF7:
        return None
    payload = unpack7(msg[1:-1])
    if len(payload) < 6 or payload[:2] != MAGIC:
        return None
    cmd = payload[2]
    ln = int.from_bytes(payload[3:6], "little")
    data = payload[6:6 + ln]
    chk = payload[6 + ln] if len(payload) > 6 + ln else None
    if chk is not None and chk != ((~sum(data)) & 0xFF):
        print(f"  (checksum mismatch: got 0x{chk:02X})")
    return cmd, data


# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------

class RtMidiTransport:
    def __init__(self, port_name_substring: str):
        import rtmidi  # noqa: PLC0415
        self.out = rtmidi.MidiOut()
        ports = self.out.get_ports()
        matches = [p for p in ports if port_name_substring.lower() in p.lower()]
        if not matches:
            raise SystemExit(
                f"no MIDI port matching '{port_name_substring}'. "
                f"Available: {ports or 'none'}"
            )
        self.out.open_port(ports.index(matches[0]))
        self.inp = rtmidi.MidiIn()
        self.inp.open_port(next(
            (i for i, p in enumerate(self.inp.get_ports())
             if port_name_substring.lower() in p.lower()), 0))
        self.inp.ignore_types(sysex=False)
        self.name = matches[0]

    def send(self, msg: bytes) -> None:
        self.out.send_message(list(msg))

    def drain(self, seconds: float):
        deadline = time.time() + seconds
        while time.time() < deadline:
            msg = self.inp.get_message()
            if msg:
                yield msg[0]


class AmidiTransport:
    def __init__(self, port: str):
        import subprocess  # noqa: PLC0415
        self.port = port
        self.amidi = "amidi"
        probe = subprocess.run([self.amidi, "-p", port, "-s", "/dev/null"],
                               capture_output=True)
        if probe.returncode != 0 and b"Invalid argument" not in probe.stderr:
            raise SystemExit(f"amidi cannot open {port}: {probe.stderr.decode()}")

    def send(self, msg: bytes) -> None:
        import subprocess  # noqa: PLC0415
        hexstr = " ".join(f"{b:02X}" for b in msg)
        subprocess.run([self.amidi, "-p", self.port, "-S", hexstr], check=True)

    def drain(self, seconds: float):
        import subprocess  # noqa: PLC0415
        out = subprocess.run([self.amidi, "-p", self.port, "-d", "-t", str(seconds)],
                             capture_output=True)
        for line in out.stdout.decode().splitlines():
            if line.strip():
                yield bytes.fromhex(line)


def open_transport(port: str):
    try:
        import rtmidi  # noqa: F401,PLC0415
        return RtMidiTransport(port)
    except ImportError:
        return AmidiTransport(port)


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------

def probe_identify(tp) -> None:
    print(f"[identify] sending SysEx 0x11 to {tp.name} ...")
    tp.send(frame(0x11))
    for msg in tp.drain(2.0):
        parsed = parse_sysex(bytes(msg))
        if parsed:
            cmd, data = parsed
            printable = data.rstrip(b"\x00")
            print(f"  reply: cmd=0x{cmd:02X} data={printable!r}")
            if b"SINCO" in data:
                print("  -> transport confirmed: this is a Cube Baby-family pedal.")
                return
    print("  no valid SysEx reply. Wrong port, or the model uses a different magic.")


def probe_pc(tp) -> None:
    print("[program change] sending C0 00..05, 2 s apart.")
    print("Watch the pedal: preset LED switching = PC works.")
    for pc in range(6):
        print(f"  PC {pc} ...")
        tp.send(bytes([0xC0, pc]))
        time.sleep(2.0)
    print("Note which PC numbers changed the preset/sound.")


def probe_cc(tp) -> None:
    print("[control change] sweeping common CCs (value 0 then 127).")
    print("Watch/listen: any change reveals a live CC mapping.")
    ccs = [1, 7, 11, 20, 21, 22, 23, 24, 25, 26, 27, 28, 50, 51, 52]
    for cc in ccs:
        for val in (0, 127):
            print(f"  CC {cc} = {val}")
            tp.send(bytes([0xB0, cc, val]))
            time.sleep(0.5)
        time.sleep(0.5)


def probe_live(tp) -> None:
    print("[live edit] SysEx single-byte preset writes (edit buffer only).")
    print("Known-good only for the Cube Baby AC memory map (bank 5).")
    print("Sweeping preset A VOLUME (offset 0x05) 0 -> 127 -> 0.")
    for val in list(range(0, 128, 16)) + list(range(112, -1, -16)):
        addr = 0x80000000 + 0 * 16 + 0x05
        data = addr.to_bytes(4, "little") + bytes([val])
        print(f"  VOLUME = {val}")
        tp.send(frame(0x22, data))
        time.sleep(0.3)
    print("If the volume moved, the SysEx live-edit path works on your model.")


PROBES = {"identify": probe_identify, "pc": probe_pc, "cc": probe_cc,
          "live": probe_live}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", action="store_true", help="list MIDI ports and exit")
    ap.add_argument("--port", default="hw:1", help="MIDI port (amidi) or name substring (rtmidi)")
    ap.add_argument("probe", nargs="?", choices=sorted(PROBES), help="probe to run")
    args = ap.parse_args()

    if args.list:
        try:
            import rtmidi  # noqa: PLC0415
            for p in rtmidi.MidiOut().get_ports():
                print(p)
        except ImportError:
            try:
                import subprocess  # noqa: PLC0415
                res = subprocess.run(["amidi", "-l"], capture_output=True)
                print(res.stdout.decode(), end="")
            except FileNotFoundError:
                print("No transport found: install python-rtmidi (pip install rtmidi)"
                      " or alsa-utils (amidi).")
        return 0

    if not args.probe:
        ap.error("choose a probe: " + ", ".join(sorted(PROBES)))

    tp = open_transport(args.port)
    PROBES[args.probe](tp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
