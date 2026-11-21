"""Discover batches and map script paths to safe, atomic output files."""

from __future__ import annotations

import ntpath
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

import mmh3

from .errors import ScriptError
from .pipeline import SOURCE_COMMANDS, UNPACK_COMMANDS

_OUTPUT_SUFFIX = {
    "decrypt": ".pyc", "deobfuscate": ".pyc", "decompile": ".py", "unpack": ".py",
    "compile": ".pyc", "obfuscate": ".pyc", "encrypt": ".enc", "pack": ".enc",
}
_BYTECODE_SUFFIXES = {".pyc", ".pyo", ".marshal"}
_NPK_HASH_SEED = 0x9747B28C

# ntpath handles Windows device names even on a POSIX host.
_windows_reserved = getattr(ntpath, "isreserved", lambda part: PureWindowsPath(part).is_reserved())


@dataclass(frozen=True)
class Input:
    path: Path
    relative: PurePosixPath


def discover(input_path: Path, output: Path, command: str) -> list[Input]:
    if input_path.is_file():
        return [Input(input_path, PurePosixPath(input_path.name))]
    if not input_path.is_dir():
        raise ScriptError(f"input does not exist or is not a regular file or directory: {input_path}")

    if command in SOURCE_COMMANDS:
        suffixes = {".py"}
    elif command in {"decrypt", "unpack"}:
        suffixes = {".enc", ".nxs"}
    else:
        suffixes = _BYTECODE_SUFFIXES

    skip_output = output != input_path and output.is_relative_to(input_path)
    files = []
    for directory, subdirs, names in os.walk(input_path, onerror=_raise_walk_error):
        root = Path(directory)
        if skip_output:
            subdirs[:] = [name for name in subdirs if root / name != output]
        for name in names:
            path = root / name
            if path.suffix.lower() in suffixes and path.is_file():
                files.append(Input(path, PurePosixPath(path.relative_to(input_path).as_posix())))
    return sorted(files, key=lambda item: item.relative.as_posix())


def _raise_walk_error(error: OSError) -> None:
    raise error


def portable_path(text: str) -> PurePosixPath:
    path = text.replace("\\", "/")
    windows = PureWindowsPath(path)
    parts = path.split("/")
    if (not path or windows.anchor or path.startswith("<") or
            any(part in ("", ".", "..") or part.endswith((".", " ")) or
                re.search(r'[\x00-\x1f<>:"|?*]', part) or _windows_reserved(part)
                for part in parts)):
        raise ScriptError(f"expected a portable relative script path, got {text!r}")
    return PurePosixPath(path)


def archive_name(path: PurePosixPath) -> str:
    """Match the flat entry ID naming used for extracted NeoX scripts."""
    if len(path.parts) > 1 and path.parts[0] == "lib":
        path = PurePosixPath(*path.parts[1:])
    archive_path = path.with_suffix(".nxs").as_posix().replace("/", "\\")
    entry_id = mmh3.hash(archive_path.encode("utf-8", "surrogateescape"), _NPK_HASH_SEED, signed=False)
    return f"{entry_id:08x}.enc"


def output_relative(command: str, relative: PurePosixPath, embedded: bytes | None) -> PurePosixPath:
    suffix = _OUTPUT_SUFFIX[command]
    if command in UNPACK_COMMANDS or suffix == ".enc":
        if embedded is None:
            raise ScriptError("bytecode has no embedded filename")
        try:
            source_path = portable_path(embedded.decode("utf-8", "surrogateescape"))
        except ScriptError:
            source_path = portable_path(relative.as_posix())
        if suffix == ".enc":
            return PurePosixPath(archive_name(source_path))
        return source_path.with_suffix(suffix)
    return relative.with_suffix(suffix)


def output_destination(root: Path, relative: PurePosixPath) -> Path:
    target = root.joinpath(*relative.parts)
    if not target.resolve().is_relative_to(root):
        raise ScriptError(f"output path escapes its folder: {relative}")
    return target


def write_output(target: Path, data: bytes, *, overwrite: bool) -> bool:
    """Publish a completed output. Return False when the existing file is kept."""
    if not overwrite and target.exists():
        if target.is_file():
            return False
        raise ScriptError(f"output path is not a file: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".nxscript-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        if overwrite:
            os.replace(temporary, target)
        else:
            try:
                if os.name == "nt":
                    os.rename(temporary, target)
                else:
                    os.link(temporary, target)
            except FileExistsError:
                if target.is_file():
                    return False
                raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return True
