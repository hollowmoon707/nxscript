"""Compose the conversion stages without writing intermediate files."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import PurePosixPath
from typing import Callable

from . import crypto, opcodes
from .bytecode import Bytecode, MarshalCode
from .rotor import default_rotor
from .runtime import PythonRuntime

PIPELINES = {
    "decrypt": ("decrypt",),
    "deobfuscate": ("deobfuscate",),
    "decompile": ("decompile",),
    "unpack": ("decrypt", "deobfuscate", "decompile"),
    "encrypt": ("encrypt",),
    "obfuscate": ("obfuscate",),
    "compile": ("compile",),
    "pack": ("compile", "obfuscate", "encrypt"),
}
SOURCE_COMMANDS = {"compile", "pack"}
UNPACK_COMMANDS = {"decrypt", "deobfuscate", "decompile", "unpack"}


class Conversion:
    """A command with resources reused across all inputs in its batch."""

    def __init__(self, command: str):
        self.command = command
        self.steps = PIPELINES[command]
        self.rotor = default_rotor() if {"encrypt", "decrypt"}.intersection(self.steps) else None
        self.runtime: PythonRuntime | None = None
        self._resources = ExitStack()

    def __enter__(self) -> Conversion:
        for mode in ("compile", "decompile"):
            if mode in self.steps:
                self.runtime = self._resources.enter_context(PythonRuntime(mode))
                try:
                    self.runtime.start()
                except BaseException:
                    self._resources.close()
                    raise
        return self

    def __exit__(self, *exc_info):
        self._resources.__exit__(*exc_info)

    def process(
        self,
        input_data: bytes,
        relative_path: PurePosixPath,
        on_step: Callable[[str], None],
    ) -> tuple[bytes, bytes | None]:
        """Return output bytes and the embedded source filename, where relevant."""
        data = input_data
        embedded = None
        for step in self.steps:
            if step == "decrypt":
                payload = crypto.decrypt(data, self.rotor)
                embedded = MarshalCode(payload).filename
                data = Bytecode(payload).to_pyc()
            elif step == "compile":
                filename = relative_path.as_posix().replace("/", "\\").encode("utf-8")
                data = Bytecode(self.runtime.convert(data, filename)).to_pyc()
                embedded = filename
            else:
                bytecode = Bytecode.read(data)
                if step == "encrypt":
                    if embedded is None:
                        embedded = MarshalCode(bytecode.payload).filename
                    data = crypto.encrypt(bytecode.payload, self.rotor)
                elif step == "obfuscate":
                    data = Bytecode(opcodes.obfuscate(bytecode.payload), bytecode.header).to_pyc()
                elif step == "deobfuscate":
                    if embedded is None:
                        embedded = MarshalCode(bytecode.payload).filename
                    data = Bytecode(opcodes.deobfuscate(bytecode.payload), bytecode.header).to_pyc()
                elif step == "decompile":
                    if embedded is None:
                        embedded = MarshalCode(bytecode.payload).filename
                    data = self.runtime.convert(bytecode.to_pyc())
            on_step(step)
        return data, embedded
