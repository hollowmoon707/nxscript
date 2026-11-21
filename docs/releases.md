# nxscript releases

Choose the Windows x64 or Ubuntu x64 archive for your machine. Ubuntu bundles
are built on Ubuntu 22.04.

## Bundled

Extract the whole archive and run `nxscript.exe` on Windows or `./nxscript`
on Ubuntu from the extracted directory. The archive includes a modern
Python 3 runtime for the CLI, and stock CPython 2.7.3 with uncompyle6 for the
compile and decompile workers. Keep the executable with its `_internal` folder.

## Unbundled

Install Python 3.10 or newer. Extract the archive, open a terminal in the
extracted directory, and install its wheel into a virtual environment.

On Windows PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install (Get-ChildItem *.whl).FullName
.\.venv\Scripts\nxscript.exe --help
```

On Ubuntu:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install ./*.whl
.venv/bin/nxscript --help
```

Pip downloads the CLI's dependencies. Stock CPython 2.7.3 is required for
`compile` and `pack`. For `decompile` and `unpack`, use stock CPython 2.7
with a compatible uncompyle6 installed. The same runtime can serve both.
Set `NXSCRIPT_PY27` and `NXSCRIPT_DECOMPILER_PYTHON` to the corresponding
absolute executable paths. The other four commands only need Python 3.

## Building releases

The **Release** workflow runs the native builds on Windows Server 2022 and
Ubuntu 22.04. It extracts the official stock Windows MSI into a staging
directory and builds stock CPython on Ubuntu. Each runner freezes the
Python 3 CLI, builds the wheel, and smoke-tests both archives after extraction.

Use **Run workflow** in the Actions tab to validate the two builds and
download their artifacts. For a public release, push a version tag matching
the version in `pyproject.toml`. After both build jobs pass, the workflow
publishes all four archives to one GitHub Release. The runtime comes from
python.org and the decompiler dependencies come from PyPI.
