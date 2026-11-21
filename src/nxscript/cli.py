"""Command-line entry point for the eight NeoX script conversions."""

import argparse
import os
from pathlib import Path
from time import monotonic

from . import __version__, ui
from .errors import ScriptError
from .files import discover, output_destination, output_relative, portable_path, write_output
from .pipeline import Conversion, SOURCE_COMMANDS

_HELP = {
    "decrypt": "Decrypt entries to obfuscated Python 2.7 .pyc files",
    "deobfuscate": "Convert NeoX bytecode to stock Python 2.7 bytecode",
    "decompile": "Decompile stock Python 2.7 bytecode to source",
    "unpack": "Decrypt, deobfuscate, and decompile entries to source",
    "encrypt": "Wrap Python 2.7 bytecode as encrypted NeoX entries",
    "obfuscate": "Apply direct NeoX opcode substitution to stock bytecode",
    "compile": "Compile source with stock CPython 2.7.3",
    "pack": "Compile, obfuscate, and encrypt source as NeoX entries",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nxscript", description="Convert individual NeoX script files.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in _HELP.items():
        command = commands.add_parser(name, help=help_text, description=help_text)
        command.add_argument("--in", dest="input", type=Path, required=True, help="input file or directory")
        command.add_argument("--out", type=Path, required=True, help="output directory")
        command.add_argument("--overwrite", action="store_true", help="replace existing output files")
        if name in SOURCE_COMMANDS:
            command.add_argument("--path", metavar="RELATIVE.py", help="embedded path for single-file input")
    return parser


def run(args: argparse.Namespace) -> int:
    started = monotonic()
    input_path, output = args.input.expanduser().absolute(), args.out.expanduser().resolve()
    if input_path.is_dir():
        input_path = input_path.resolve()
    script_path = getattr(args, "path", None)
    if script_path is not None:
        if not input_path.is_file():
            raise ScriptError("--path requires a single input file")
        script_path = portable_path(script_path)
        if script_path.suffix.lower() != ".py":
            raise ScriptError("--path must end in .py")
    if output.exists() and not output.is_dir():
        raise ScriptError(f"--out is not a directory: {output}")

    ui.banner(args.command)
    with ui.console.status("Finding input files", spinner="dots"):
        files = discover(input_path, output, args.command)
    if not files:
        raise ScriptError(f"no matching files under {input_path}")

    conversion = Conversion(args.command)
    summary = ui.Summary(dict.fromkeys(conversion.steps, 0))
    claimed = {}
    with conversion, ui.StageProgress(conversion.steps, len(files)) as progress:
        def step_completed(step: str) -> None:
            summary.step_completed(step)
            progress.completed(step)

        for item in files:
            relative = script_path or item.relative
            try:
                if args.command in SOURCE_COMMANDS:
                    relative = portable_path(relative.as_posix())
                data, embedded = conversion.process(item.path.read_bytes(), relative, step_completed)
                destination = output_relative(args.command, relative, embedded)
                target = output_destination(output, destination)
                key = os.path.normcase(str(target.resolve()))
                if key in claimed:
                    raise ScriptError(f"output {destination} also belongs to {claimed[key]}")
                if write_output(target, data, overwrite=args.overwrite):
                    summary.written += 1
                else:
                    summary.kept += 1
                claimed[key] = item.relative
            except (OSError, ScriptError, UnicodeError, ValueError) as exc:
                summary.report_error(item.relative.as_posix(), str(exc))
            progress.completed("Processed")
    summary.show(monotonic() - started)
    return int(summary.failed > 0)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (OSError, ScriptError) as exc:
        ui.error(str(exc))
        return 1
    except KeyboardInterrupt:
        ui.error("Interrupted")
        return 130
