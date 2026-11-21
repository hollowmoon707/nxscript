"""The 'rotor' cipher (stage 1 core).

NeoX re-added Andrew Kuchling's old CPython-2 ``rotor`` module (an Enigma-style
rotor machine) to its embedded Python 2.7 and uses it to encrypt every script.
This is a clean re-implementation of that algorithm, recovered from the engine
binary and cross-checked against the reference port in NeoXtractor.

It is *processing logic*, not game data. The one game-specific value is the key,
assembled below from the three string fragments the engine's ``init_rotor`` holds.
The key is a cipher parameter (like an XOR constant), not a bundled asset; it can
be overridden on the command line.

Algorithm, for a key of bytes k and ``nrotors`` rotors over an alphabet of ``size``:

* Seed three 16-bit Wichmann-Hill generators from the key (rotate-left-3, then
  +/^/- each key byte), force the middle seed odd, then take one overflow-safe
  Schrage step so the first draw is well mixed.
* Build each rotor: a random start position, an odd advance step, and a
  Fisher-Yates permutation ``E`` with its inverse ``D`` (index ``size`` of each
  array holds the advance step).
* Encrypt/decrypt a byte by running it through the rotors, then step the rotors
  like an odometer: each rotor advances by its step, carrying into the next.

The odometer carry is the subtle part: a rotor's new position is
``((pos + carry_in) & 0xFF) + step`` taken ``mod size``, and the carry out is
whether that sum reached ``size`` *before* the modulo. Getting this wrong only
shows up after a wraparound, which is why a near-miss still fails to inflate.
"""

from __future__ import annotations

# The three fragments init_rotor() holds, and the order it assembles them in.
_FRAGMENTS = ("j2h56ogodh3se", "=dziaq.", '|os=5v7!"-234')


def default_key() -> bytes:
    """The recovered HPMA script key (297 bytes)."""
    dn, dt, df = _FRAGMENTS
    key = dn * 4 + (dt + dn + df) * 5 + "!#" + dt * 7 + df * 2 + "*&'"
    return key.encode("latin-1")


class Rotor:
    """A rotor machine. ``encrypt`` and ``decrypt`` are exact inverses.

    The rotor tables depend only on the key, so they are built once and reused;
    each call restarts the rotor positions from their initial values.
    """

    def __init__(self, key: bytes | str, nrotors: int = 6, size: int = 256) -> None:
        if isinstance(key, str):
            key = key.encode("latin-1")
        self.key = bytes(key)
        self.nrotors = nrotors
        self.size = size
        self._forward: tuple[tuple[int, ...], ...] | None = None  # E rotors
        self._reverse: tuple[tuple[int, ...], ...] | None = None  # D rotors
        self._start: tuple[int, ...] | None = None                # initial positions

    # -- key schedule ----------------------------------------------------------------------------

    def _seeded_rng(self):
        """A pseudo-random draw(n) -> int in [0, n), seeded from the key."""
        mask = 0xFFFF
        x, y, z = 995, 576, 767
        for byte in self.key:
            x = ((x << 3 | x >> 13) + byte) & mask
            y = ((y << 3 | y >> 13) ^ byte) & mask
            z = ((z << 3 | z >> 13) - byte) & mask

        half = mask >> 1
        if x > half:
            x -= mask + 1
        if y > half:
            y -= mask + 1
        if z > half:
            z -= mask + 1
        y |= 1

        # one Schrage step == (a * seed) % m, done the overflow-safe way the C code uses
        x = 171 * (x % 177) - 2 * (x // 177)
        y = 172 * (y % 176) - 35 * (y // 176)
        z = 170 * (z % 178) - 63 * (z // 178)
        if x < 0:
            x += 30269
        if y < 0:
            y += 30307
        if z < 0:
            z += 30323

        state = [x, y, z]

        def draw(n: int) -> int:
            cx, cy, cz = state
            value = int((cx / 30269.0 + cy / 30307.0 + cz / 30323.0) * n) % n
            state[0] = (171 * cx) % 30269
            state[1] = (172 * cy) % 30307
            state[2] = (170 * cz) % 30323
            return value

        return draw

    def _ensure_built(self) -> None:
        if self._forward is not None:
            return
        size, nrotors = self.size, self.nrotors
        draw = self._seeded_rng()
        identity = list(range(size + 1))
        forward: list[tuple[int, ...]] = []
        reverse: list[tuple[int, ...]] = []
        start: list[int] = []
        for _ in range(nrotors):
            start.append(draw(size))
            e = identity[:]
            d = identity[:]
            step = 1 + 2 * draw(size // 2)        # odd advance step
            e[size] = d[size] = step              # stored past the alphabet
            i = size
            while i > 1:
                r = draw(i)
                i -= 1
                e[r], e[i] = e[i], e[r]
                d[e[i]] = i
            d[e[0]] = 0
            forward.append(tuple(e))
            reverse.append(tuple(d))
        self._forward = tuple(forward)
        self._reverse = tuple(reverse)
        self._start = tuple(start)

    # -- the odometer ----------------------------------------------------------------------------

    def _advance(self, pos: list[int], rotors: tuple[tuple[int, ...], ...]) -> None:
        size = self.size
        carry = 0
        for i in range(self.nrotors):
            total = ((pos[i] + carry) & 0xFF) + rotors[i][size]
            pos[i] = total % size
            carry = 1 if total >= size else 0

    # -- the cipher ------------------------------------------------------------------------------

    def decrypt(self, data: bytes) -> bytes:
        self._ensure_built()
        reverse = self._reverse
        pos = list(self._start)                # type: ignore[arg-type]
        out = bytearray(len(data))
        for k, c in enumerate(data):
            for i in range(self.nrotors - 1, -1, -1):
                c = pos[i] ^ reverse[i][c]
            out[k] = c & 0xFF
            self._advance(pos, reverse)
        return bytes(out)

    def encrypt(self, data: bytes) -> bytes:
        self._ensure_built()
        forward = self._forward
        pos = list(self._start)                # type: ignore[arg-type]
        out = bytearray(len(data))
        for k, c in enumerate(data):
            for i in range(self.nrotors):
                c = forward[i][c ^ pos[i]]
            out[k] = c & 0xFF
            self._advance(pos, forward)
        return bytes(out)


def default_rotor() -> Rotor:
    """A Rotor keyed with the recovered HPMA script key (6 rotors, size 256)."""
    return Rotor(default_key())
