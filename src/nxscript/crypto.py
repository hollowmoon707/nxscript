"""Convert between a NeoX script entry and its decrypted marshal payload."""

import zlib

from .errors import ScriptError
from .rotor import Rotor, default_rotor

_XOR = bytes(value ^ 0x9A for value in range(256))
MAX_MARSHAL_SIZE = 64 * 1024 * 1024


def _mask_head(data: bytes) -> bytes:
    return data[:128].translate(_XOR) + data[128:]


def decrypt(entry: bytes, rotor: Rotor | None = None) -> bytes:
    """Read an encrypted entry or a bare marshal entry such as redirect.nxs."""
    if entry.startswith(b"c"):
        return entry

    compressed = (rotor or default_rotor()).decrypt(entry)
    inflater = zlib.decompressobj()
    try:
        masked = inflater.decompress(compressed, MAX_MARSHAL_SIZE + 1)
    except zlib.error as exc:
        raise ScriptError(f"invalid NeoX wrapper ({exc})") from exc
    if len(masked) > MAX_MARSHAL_SIZE or inflater.unconsumed_tail:
        raise ScriptError(f"decrypted marshal exceeds {MAX_MARSHAL_SIZE:,} bytes")
    if not inflater.eof:
        raise ScriptError("incomplete zlib stream in NeoX wrapper")
    if inflater.unused_data:
        raise ScriptError("trailing bytes after the NeoX wrapper")
    return _mask_head(masked)[::-1]


def encrypt(payload: bytes, rotor: Rotor | None = None) -> bytes:
    """Apply the NeoX wrapper to a marshal payload, leaving its opcodes intact."""
    if len(payload) > MAX_MARSHAL_SIZE:
        raise ScriptError(f"marshal exceeds {MAX_MARSHAL_SIZE:,} bytes")
    return (rotor or default_rotor()).encrypt(zlib.compress(_mask_head(payload[::-1])))
