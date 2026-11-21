# Usage and file layout

## Unpack in stages

```sh
nxscript decrypt --in unpacked/script/_unnamed --out decoded
nxscript deobfuscate --in decoded --out stock
nxscript decompile --in stock --out recovered
```

This produces the same source as `nxscript unpack`. Each stage writes a
separate tree when called individually. The embedded source path in the
outermost code object determines the output path. If the embedded name is
absolute, synthetic, or unsafe to write, nxscript uses the input's relative
path. Both slash styles are accepted in embedded paths.

`decrypt` and `unpack` look for `.enc` and `.nxs` in directories. The
unwrapped bootstrap can be passed explicitly even if the extractor assigned
it a `.bin` extension. For a bytecode directory, nxscript accepts `.pyc`,
`.pyo`, and `.marshal`. A single bytecode file is recognized by its contents.
The `.pyc` produced by `decrypt` contains NeoX opcodes. Run
`deobfuscate` before feeding that file to a stock Python interpreter or
decompiler.

## Pack in stages

```sh
nxscript compile --in recovered --out stock
nxscript obfuscate --in stock --out neo
nxscript encrypt --in neo --out entries
```

These stages produce the same encrypted entries as `nxscript pack`. For a
directory of edits, every source filename is baked in relative to the input
root, with backslashes for NeoX. For a single file, the path defaults to its
basename. Use `--path` on `compile` or `pack` to supply the original
relative source path when compiling from a different location.

`compile` and `obfuscate` keep the relative filesystem tree. `encrypt`
uses the embedded source filename to produce a flat eight-digit entry ID
with the `.enc` extension. It hashes the case-sensitive path with backslashes
and the `.nxs` suffix. For a script under `lib/`, the archive lookup uses the
path relative to `lib/`. If the embedded name is unusable, the same hash uses
the input-relative path. `encrypt` wraps the supplied bytecode regardless
of the opcode encoding. Use `obfuscate` or `pack` when preparing stock
bytecode for NeoX.

Archive construction is a separate step. The original NeoX bootstrap
`redirect.nxs` is stored as bare marshal and has its own loading rules.

## Batch results

During an interactive run, each stage displays a completed-file counter.
The summary includes the number of files written, kept, and failed. At most
12 representative failures are displayed. A duplicate destination within a
run counts as a failure, even with `--overwrite`. Use separate output
directories for intermediate bytecode, particularly for the two opcode
representations that share the `.pyc` extension.
