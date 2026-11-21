# Design and format

## Three stages

- `crypto.py` converts between an extracted entry and bare Python 2.7 marshal.
  It reverses the draft wrapper with rotor decryption, zlib inflation, XOR
  of the first 128 bytes with `0x9A`, and byte reversal. Encryption applies
  the inverse. A standard eight-byte Python 2.7 header is added when exposing
  decrypted marshal as `.pyc`.
- `opcodes.py` translates opcodes in every code object, including nested
  functions. The marshal scanner in `bytecode.py` rewrites only the changed
  fields, preserving the serialization of constants and other metadata.
  Direct substitution for `obfuscate` preserves instruction widths.
  Deobfuscation consumes continuation operands according to the table and
  expands fused instructions. It maps the original instruction boundaries to
  stock byte offsets, then relocates absolute jumps, relative jumps, and the
  line table. If a moved target needs `EXTENDED_ARG`, the layout is recomputed
  with the extra prefix bytes. When fusion has merged an original line start
  into a single encoded instruction, the recovered line can begin at that
  instruction's first stock sub-operation.
- `runtime.py` launches a reusable stock Python process for the batch.
  Compilation calls Python 2.7.3's `compile` with the embedded entry path.
  Decompilation uses native `uncompyle6` with a stock 2.7 `.pyc`, and checks
  that the resulting source parses. For large list, tuple, set, and dictionary expressions, including
  common metadata wrapper calls, the worker temporarily substitutes a short
  marker before decompilation and restores the literal in the emitted source.
  This keeps the literal out of the parser's expensive grammar pass while
  retaining its assignment or surrounding call and the rest of the module.

`pipeline.py` connects the stages in memory. The CLI owns discovery, output
paths and the terminal UI. Neither compilation nor decompilation imports or
executes the scripts being converted. Decompiled source can differ in layout
and comments from the original. Repacked entries use direct opcode substitution,
so their encoded bytes can differ from entries that use fusion.

## Opcode table updates

The authoritative files are `opdirect.csv`, `opfused.csv`, `opprev.csv`,
and `opindex.csv` under the project research directory
`nxdocs/packaging/scripts`. Run the generator from this repository to regenerate
and verify the checked-in Python module.

```sh
python3 tools/generate_opcodes.py /path/to/HPMA_PROJECT/nxdocs/packaging/scripts
python3 tools/generate_opcodes.py /path/to/HPMA_PROJECT/nxdocs/packaging/scripts --check
```

The generator checks the direct mapping, instruction widths, operand
sources, and coverage against the index. Its output is sorted by opcode and
contains no game scripts. Converted bytecode is never bundled with nxscript.

## Runtime discovery and future bundles

`NXSCRIPT_PY27` selects the compiler. `NXSCRIPT_DECOMPILER_PYTHON` selects
the decompiler process. Without an explicit setting, nxscript checks for a
runtime next to the installed package under `runtime/bin/python2.7` on Linux
or `runtime/python.exe` on Windows. It also looks for a local
`~/py273` install and Python 2 on PATH. The decompiler also tries the
compiler override and the local `~/py27` runtime when available. The worker
checks the Python version and imports `uncompyle6` before starting a batch.

The worker is a regular package file invoked via the selected executable.
Bundling a stock runtime later can use the same entry point for an installed
package or an application directory. A runtime used for decompilation also
needs a compatible Python 2 release of `uncompyle6` and its dependencies.
The project's local Python 2 installation uses `uncompyle6 3.2.6`.
