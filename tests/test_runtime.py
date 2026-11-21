from pathlib import PurePosixPath

import pytest

from nxscript.bytecode import Bytecode, MarshalCode
from nxscript.crypto import decrypt
from nxscript.errors import ScriptError
from nxscript.opcodes import deobfuscate, obfuscate
from nxscript.pipeline import Conversion
from nxscript.runtime import PythonRuntime


def test_runtime_roundtrip_keeps_large_literals_wrappers_and_nested_code():
    path = PurePosixPath("folder/item.py")
    values = ", ".join("%d: keep([%d, %d, True])" % (i, i, i + 1) for i in range(350))
    original = ("def keep(value):\n    return value\n"
                "data = keep({%s})\n"
                "answer = data[349][1]\n" % values).encode("ascii")
    with PythonRuntime("compile") as compiler, PythonRuntime("decompile") as decompiler:
        try:
            compiler.start()
            decompiler.start()
        except ScriptError as exc:
            pytest.skip(str(exc))
        payload = compiler.convert(original, b"folder\\item.py")
        assert deobfuscate(obfuscate(payload)) == payload
        reconstructed = decompiler.convert(Bytecode(payload).to_pyc())
        assert b"data = keep({" in reconstructed
        assert b"349: keep([349, 350, True])" in reconstructed
        assert b"def keep(value):" in reconstructed
        compiler.convert(reconstructed, b"folder\\item.py")

    with Conversion("pack") as conversion:
        packed, filename = conversion.process(original, path, lambda _: None)
    assert filename == b"folder\\item.py"
    assert MarshalCode(decrypt(packed)).filename == filename
    assert deobfuscate(decrypt(packed)) == payload
