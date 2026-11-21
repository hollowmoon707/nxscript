"""Start and reuse the stock Python process for compilation or decompilation."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path

from .errors import ScriptError

_WORKER = Path(__file__).with_name("_py27_worker.py")


def _start_worker(command: list[str]) -> subprocess.Popen:
    options = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.DEVNULL}
    if not getattr(sys, "frozen", False):
        return subprocess.Popen(command, **options)
    if os.name == "nt":
        # PyInstaller points the DLL loader at its Python 3 libraries.
        import ctypes

        set_directory = ctypes.windll.kernel32.SetDllDirectoryW
        set_directory.argtypes = [ctypes.c_wchar_p]
        set_directory(None)
        try:
            return subprocess.Popen(command, **options)
        finally:
            set_directory(sys._MEIPASS)

    env = os.environ.copy()
    original = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if original is None:
        env.pop("LD_LIBRARY_PATH", None)
    else:
        env["LD_LIBRARY_PATH"] = original
    return subprocess.Popen(command, env=env, **options)


class PythonRuntime:
    def __init__(self, mode: str, *, timeout: float = 180):
        self.mode = mode
        self.timeout = timeout
        self.process: subprocess.Popen | None = None
        self.executable: str | None = None
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._scratch: tempfile.TemporaryDirectory | None = None

    def __enter__(self) -> PythonRuntime:
        return self

    def __exit__(self, *exc_info) -> None:
        self._stop()
        self._pool.shutdown()
        if self._scratch is not None:
            self._scratch.cleanup()

    def _candidates(self):
        setting = "NXSCRIPT_PY27" if self.mode == "compile" else "NXSCRIPT_DECOMPILER_PYTHON"
        override = os.environ.get(setting)
        if override:
            yield override
            return
        python_name = "python.exe" if os.name == "nt" else "bin/python2.7"
        here = Path(__file__).parent
        yield str(here / "runtime" / python_name)
        if self.mode == "decompile" and os.environ.get("NXSCRIPT_PY27"):
            yield os.environ["NXSCRIPT_PY27"]
        yield str(Path.home() / "py273" / python_name)
        yield from ("python2.7", "python2")
        if self.mode == "decompile":
            yield str(Path.home() / "py27" / python_name)

    def start(self) -> None:
        if self.process is not None:
            return
        worker_args = ["-B", "-u", str(_WORKER), self.mode]
        if self.mode == "decompile":
            if self._scratch is None:
                self._scratch = tempfile.TemporaryDirectory(prefix="nxscript-")
            worker_args.append(str(Path(self._scratch.name) / "script.pyc"))
        attempted = {}
        for candidate in [self.executable] if self.executable else self._candidates():
            executable = shutil.which(os.path.expanduser(candidate))
            if not executable or executable in attempted:
                continue
            try:
                self.process = _start_worker([executable, *worker_args])
                self._exchange(None, timeout=15)
            except (OSError, ScriptError) as exc:
                attempted[executable] = str(exc)
                self._stop()
            else:
                self.executable = executable
                return
        details = "; ".join(f"{name} ({error})" for name, error in attempted.items())
        if self.mode == "compile":
            hint = "set NXSCRIPT_PY27 to a stock CPython 2.7.3 executable"
        else:
            hint = "set NXSCRIPT_DECOMPILER_PYTHON to a stock CPython 2.7 with uncompyle6 installed"
        raise ScriptError(f"cannot start Python for {self.mode}; {hint}" + (f". Tried {details}" if details else ""))

    def _stop(self) -> None:
        process = self.process
        self.process = None
        if process is not None:
            process.kill()
            process.wait()
            process.stdin.close()
            process.stdout.close()

    def _io(self, request: tuple[bytes, bytes] | None):
        process = self.process
        if request is not None:
            filename, data = request
            process.stdin.write(f"{len(filename)} {len(data)}\n".encode("ascii"))
            process.stdin.write(filename)
            process.stdin.write(data)
            process.stdin.flush()
        header = process.stdout.readline(128).split()
        if len(header) != 2 or header[0] not in (b"ok", b"error") or not header[1].isdigit():
            raise OSError("worker exited or sent an invalid response")
        size = int(header[1])
        result = process.stdout.read(size)
        if len(result) != size:
            raise OSError("worker response was truncated")
        return header[0], result

    def _exchange(self, request: tuple[bytes, bytes] | None, timeout: float) -> bytes:
        future = self._pool.submit(self._io, request)
        try:
            status, result = future.result(timeout)
        except (OSError, TimeoutError) as exc:
            self._stop()
            problem = f"timed out after {timeout:g}s" if isinstance(exc, TimeoutError) else str(exc)
            raise ScriptError(f"Python {self.mode} worker {problem}") from exc
        if status == b"error":
            raise ScriptError(result.decode("utf-8", "replace"))
        return result

    def convert(self, data: bytes, filename: bytes = b"") -> bytes:
        self.start()
        return self._exchange((filename, data), self.timeout)
