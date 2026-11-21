"""Worker script launched by a stock Python 2.7 interpreter."""

import marshal
import sys

# The pipe carries binary requests and responses. Decompiler diagnostics go
# to a different stream so parser debugging cannot corrupt the protocol.
incoming = sys.stdin
outgoing = sys.stdout
sys.stdout = sys.stderr


def backend(mode):
    if sys.version_info[:2] != (2, 7) or getattr(sys, "subversion", (None,))[0] != "CPython":
        raise RuntimeError("expected stock CPython 2.7")
    if mode == "compile":
        if sys.version_info[:3] != (2, 7, 3):
            raise RuntimeError("compilation requires stock CPython 2.7.3")
        return compile_source
    from uncompyle6 import decompile_file
    return lambda filename, data: decompile_bytecode(data, decompile_file, sys.argv[2])


def compile_source(filename, data):
    return marshal.dumps(compile(data, filename, "exec", 0, True), 2)


def decompile_bytecode(data, decompile_file, path):
    from _literal27 import reduce_literals

    original = marshal.loads(data[8:])
    compact, literals = reduce_literals(original)
    if literals:
        shortened = data[:8] + marshal.dumps(compact, 2)
        try:
            return _render_bytecode(shortened, decompile_file, path, literals)
        except Exception:
            # Some uncompyle6 releases reject the shortened representation
            # of code that they can still decompile in its original form.
            pass
    return _render_bytecode(data, decompile_file, path, {})


def _render_bytecode(data, decompile_file, path, literals):
    from StringIO import StringIO
    from _literal27 import expand_literals

    output = StringIO()
    with open(path, "wb") as pyc:
        pyc.write(data)
    decompile_file(path, output)
    source = output.getvalue()
    if isinstance(source, unicode):
        source = source.encode("utf-8")
    source = expand_literals(source, literals)
    if not source.strip():
        raise ValueError("uncompyle6 returned empty source")
    # uncompyle6 may emit UTF-8 in comments or literals without a cookie.
    if any(ord(char) >= 128 for char in source):
        source = "# coding: utf-8\n" + source
    compile(source, "<decompiled>", "exec", 0, True)
    return source


def send(status, data):
    outgoing.write("%s %d\n" % (status, len(data)))
    outgoing.write(data)
    outgoing.flush()


def send_error(error):
    details = [line.strip() for line in str(error).splitlines() if line.strip()]
    message = "%s: %s" % (type(error).__name__, " ".join(details[:3]))
    send("error", message[:500])


def main():
    try:
        convert = backend(sys.argv[1])
    except Exception as error:
        send_error(error)
        return
    send("ok", "")
    while True:
        request = incoming.readline()
        if not request:
            return
        name_size, data_size = map(int, request.split())
        filename = incoming.read(name_size)
        data = incoming.read(data_size)
        if len(filename) != name_size or len(data) != data_size:
            return
        try:
            result = convert(filename, data)
        except Exception as error:
            send_error(error)
        else:
            send("ok", result)


if __name__ == "__main__":
    main()
