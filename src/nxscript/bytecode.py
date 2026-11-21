"""The Python 2.7 .pyc container and a lossless marshal code-object scanner."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .errors import ScriptError

MAGIC = b"\x03\xf3\x0d\x0a"
DEFAULT_HEADER = MAGIC + b"\0" * 4


@dataclass(frozen=True)
class Bytecode:
    payload: bytes
    header: bytes = DEFAULT_HEADER

    @classmethod
    def read(cls, data: bytes) -> Bytecode:
        if data.startswith(MAGIC) and len(data) >= 8:
            return cls(data[8:], data[:8])
        if data.startswith(b"c"):
            return cls(data)
        raise ScriptError("expected a Python 2.7 .pyc or a bare marshal code object")

    def to_pyc(self) -> bytes:
        return self.header + self.payload


@dataclass(frozen=True)
class StringField:
    start: int
    end: int
    value: bytes
    kind: bytes
    ref: int | None = None


@dataclass(frozen=True)
class CodeFields:
    instructions: StringField
    filename: StringField
    name: StringField
    lines: StringField


class MarshalCode:
    """Locate code fields without round-tripping unrelated marshal values."""

    def __init__(self, payload: bytes):
        self.payload = payload
        self._pos = 0
        self._strings: list[bytes] = []
        self._references: list[StringField] = []
        self.codes: list[CodeFields] = []
        if not payload.startswith(b"c"):
            raise ScriptError("marshal payload does not start with a Python 2.7 code object")
        try:
            self._read(b"c")
        except RecursionError as exc:
            raise ScriptError("marshal nesting exceeds the reader's recursion limit") from exc
        if self._pos != len(payload):
            raise ScriptError(f"trailing bytes after the marshal code object at offset {self._pos}")

    @property
    def filename(self) -> bytes:
        return self.codes[-1].filename.value

    def replace_strings(self, changes: list[tuple[StringField, bytes]]) -> bytes:
        patches = {}
        changed_refs = set()
        for field, data in changes:
            if data != field.value:
                kind = b"t" if field.kind == b"t" else b"s"
                patches[field.start] = (field.end, kind + struct.pack("<i", len(data)) + data)
                if kind == b"t":
                    changed_refs.add(field.ref)

        # Keep the original values of any references to a rewritten interned
        # string. The definition still takes up its original intern-table slot.
        if changed_refs:
            for field in self._references:
                if field.ref in changed_refs and field.start not in patches:
                    data = field.value
                    patches[field.start] = (field.end, b"s" + struct.pack("<i", len(data)) + data)

        parts = []
        end = 0
        for start, (next_end, replacement) in sorted(patches.items()):
            parts.extend((self.payload[end:start], replacement))
            end = next_end
        parts.append(self.payload[end:])
        return b"".join(parts)

    def _skip(self, size: int) -> int:
        start = self._pos
        if size < 0 or start + size > len(self.payload):
            raise ScriptError(f"invalid or truncated marshal field at offset {start}")
        self._pos += size
        return start

    def _take(self, size: int) -> bytes:
        return self.payload[self._skip(size):self._pos]

    def _int(self) -> int:
        return struct.unpack_from("<i", self.payload, self._skip(4))[0]

    def _count(self) -> int:
        value = self._int()
        if not 0 <= value <= len(self.payload) - self._pos:
            raise ScriptError(f"invalid marshal length {value} at offset {self._pos - 4}")
        return value

    def _read(self, expected: bytes | None = None) -> StringField | None:
        start = self._pos
        kind = self._take(1)
        if expected is not None and kind not in expected:
            raise ScriptError(f"unexpected marshal type {kind!r} at offset {start}")

        if kind in (b"s", b"t", b"R"):
            ref = None
            if kind == b"R":
                ref = self._int()
                if not 0 <= ref < len(self._strings):
                    raise ScriptError(f"invalid marshal string reference {ref} at offset {start}")
                value = self._strings[ref]
            else:
                size = self._count()
                if kind == b"s" and expected is None:
                    self._skip(size)
                    return None
                value = self._take(size)
                if kind == b"t":
                    ref = len(self._strings)
                    self._strings.append(value)
            field = StringField(start, self._pos, value, kind, ref)
            if kind == b"R":
                self._references.append(field)
            return field

        if kind == b"c":
            self._skip(16)
            instructions = self._read(b"stR")
            for _ in range(5):  # consts, names, varnames, freevars, cellvars
                self._read(b"(")
            filename = self._read(b"stR")
            name = self._read(b"stR")
            self._skip(4)  # firstlineno
            lines = self._read(b"stR")
            self.codes.append(CodeFields(instructions, filename, name, lines))
        elif kind in b"([<>":
            for _ in range(self._count()):
                self._read()
        elif kind == b"{":
            while self.payload[self._pos:self._pos + 1] != b"0":
                self._read()
                self._read()
            self._skip(1)
        elif kind == b"u":
            self._skip(self._count())
        elif kind in b"fx":
            for _ in range(2 if kind == b"x" else 1):
                self._skip(self._take(1)[0])
        elif kind == b"l":
            self._skip(2 * abs(self._int()))
        elif kind in b"iIgy":
            self._skip({b"i": 4, b"I": 8, b"g": 8, b"y": 16}[kind])
        elif kind not in b"NFTS.":
            raise ScriptError(f"unknown marshal type {kind!r} at offset {start}")
        return None
