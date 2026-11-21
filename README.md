# nxscript

Convert individual NetEase NeoX scripts between encrypted entries, Python 2.7
bytecode, and source. The opcode tables target the *Harry Potter: Magic Awakened*
NeoX build. Use `npkext` to extract the archive entries first.

## Install

With Python 3.10 or later, run the install command from this repository.

```sh
python3 -m pip install .
```

On Windows, use `py -3 -m pip install .`. The command is also available as
`python -m nxscript` in the environment where you install it.

Compilation requires stock CPython **2.7.3**. Decompilation uses `uncompyle6`
installed in a stock CPython **2.7** environment. That can be the same
interpreter. Set the executable paths if automatic discovery cannot find them.

```sh
export NXSCRIPT_PY27=/path/to/python2.7
export NXSCRIPT_DECOMPILER_PYTHON=/path/to/python2.7-with-uncompyle6
```

In PowerShell, set the variables with `$env:NXSCRIPT_PY27 = 'C:\path\python.exe'`
and `$env:NXSCRIPT_DECOMPILER_PYTHON = 'C:\path\python.exe'`. Only
`compile`, `pack`, `decompile`, and `unpack` need a Python 2 runtime. This
release ships the Python 3 package and its conversion tables.

## Usage

Extracted entries can be processed in bulk. Paths come from the script's embedded
filename, so an entry whose filename is `ui\example.py` becomes
`recovered/ui/example.py`.

```sh
nxscript unpack --in unpacked/script/_unnamed --out recovered
```

To pack an edited script, use its original relative path. `pack` produces one
flat `.enc` file named by its NeoX archive entry ID.

```sh
nxscript pack --in edits/example.py --path ui/example.py --out entries
```

| Command | Reads | Writes |
| --- | --- | --- |
| `decrypt` | Encrypted entries | NeoX-opcode `.pyc` |
| `deobfuscate` | NeoX-opcode bytecode | Stock Python 2.7 `.pyc` |
| `decompile` | Stock Python 2.7 bytecode | `.py` source |
| `unpack` | Encrypted entries | `.py` source |
| `compile` | `.py` source | Stock Python 2.7 `.pyc` |
| `obfuscate` | Stock Python 2.7 bytecode | NeoX-opcode `.pyc` |
| `encrypt` | Python 2.7 bytecode | Flat `.enc` entries |
| `pack` | `.py` source | Flat `.enc` entries |

All commands take `--in` and `--out`. Directory inputs are recursive and
existing files are kept by default. Pass `--overwrite` to replace them.
A failed input is counted and the batch continues. A batch with any failures
returns exit status 1.

See [usage and file layout](docs/usage.md) for the individual commands and
[design and format](docs/design.md) for relocation, runtime discovery, and
opcode table regeneration.

## Release downloads

The release workflow builds bundled and unbundled archives for Windows x64 and
Ubuntu x64. See [release installation and build instructions](docs/releases.md).
