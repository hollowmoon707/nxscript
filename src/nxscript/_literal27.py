"""Keep very large literal expressions out of uncompyle6's parser.

This helper runs inside stock CPython 2.7. It replaces complete literal
expressions with temporary string constants and restores the expressions in
the resulting source. Calls, assignments and surrounding code stay intact.
"""

import bisect
import dis
import itertools
import keyword
import opcode
import os
import re
import struct
import types

_MIN_LITERAL_BYTES = 384
_LOAD = opcode.opmap["LOAD_CONST"]
_MAP = opcode.opmap["BUILD_MAP"]
_STORE_MAP = opcode.opmap["STORE_MAP"]
_CALL = opcode.opmap["CALL_FUNCTION"]
_NAME_LOADS = {opcode.opmap["LOAD_NAME"], opcode.opmap["LOAD_GLOBAL"]}
_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z_0-9]*\Z")
_BUILD = dict((opcode.opmap[name], kind) for name, kind in (
    ("BUILD_LIST", "list"), ("BUILD_TUPLE", "tuple"), ("BUILD_SET", "set"),
))
_LITERAL_OPS = set(_BUILD).union(_NAME_LOADS, (_LOAD, _MAP, _STORE_MAP, _CALL))


def _instructions(data):
    offset = 0
    while offset < len(data):
        start = offset
        operation = ord(data[offset])
        offset += 1
        operand = 0
        while operation >= opcode.HAVE_ARGUMENT:
            operand |= struct.unpack_from("<H", data, offset)[0]
            offset += 2
            if operation != opcode.EXTENDED_ARG:
                break
            operation = ord(data[offset])
            offset += 1
            operand <<= 16
        yield start, offset, operation, operand


def _scalar(value):
    kind = type(value)
    if kind is str:
        return "b" + repr(value)
    if kind is tuple:
        parts = [_scalar(part) for part in value]
        if None in parts:
            return None
        return "(" + ", ".join(parts) + ("," if len(parts) == 1 else "") + ")"
    if kind in (type(None), bool, unicode, int, long, float, complex):
        text = repr(value)
        if kind in (float, complex) and ("nan" in text or "inf" in text):
            return None
        return text
    return None


class _Literal(object):
    __slots__ = ("start", "end", "kind", "value")

    def __init__(self, start, end, kind, value):
        self.start = start
        self.end = end
        self.kind = kind
        self.value = value

    def render(self, depth=0):
        if self.kind in ("scalar", "name"):
            return self.value
        if self.kind == "call":
            function, args = self.value
            return function.render(depth) + "(" + ", ".join(arg.render(depth) for arg in args) + ")"
        if self.kind == "dict":
            parts = [key.render(depth + 1) + ": " + value.render(depth + 1)
                     for key, value in self.value]
        else:
            parts = [item.render(depth + 1) for item in self.value]
        left, right = {"list": ("[", "]"), "tuple": ("(", ")"),
                       "dict": ("{", "}"), "set": ("{", "}")}[self.kind]
        if not parts:
            return left + right
        if all(len(part) < 70 for part in parts) and sum(map(len, parts)) + 2 * len(parts) <= 76:
            comma = "," if self.kind == "tuple" and len(parts) == 1 else ""
            return left + ", ".join(parts) + comma + right
        pad = "    " * depth
        return left + "\n" + "".join(pad + "    " + part + ",\n" for part in parts) + pad + right


def _literal_run(instructions, constants, names):
    stack = []
    for start, end, operation, operand in instructions:
        if operation == _LOAD:
            text = _scalar(constants[operand])
            stack.append(_Literal(start, end, "scalar", text) if text is not None else None)
        elif operation in _NAME_LOADS:
            name = names[operand]
            text = name if _IDENTIFIER.match(name) and not keyword.iskeyword(name) else None
            stack.append(_Literal(start, end, "name", text) if text is not None else None)
        elif operation == _CALL:
            count = operand + 1  # callable plus positional arguments
            if len(stack) < count:
                return []
            values = stack[-count:]
            del stack[-count:]
            if None in values or values[0].kind != "name":
                stack.append(None)
            else:
                stack.append(_Literal(values[0].start, end, "call", (values[0], values[1:])))
        elif operation == _MAP:
            stack.append(_Literal(start, end, "dict", []))
        elif operation == _STORE_MAP:
            if len(stack) < 3:
                return []
            key, value = stack.pop(), stack.pop()
            mapping = stack[-1]
            if mapping is None or mapping.kind != "dict" or key is None or value is None:
                stack[-1] = None
            else:
                mapping.value.append((key, value))
                mapping.end = end
        else:
            if operand > len(stack):
                return []
            parts = []
            if operand:
                parts = stack[-operand:]
                del stack[-operand:]
            if None in parts or (not parts and _BUILD[operation] == "set"):
                stack.append(None)
            else:
                stack.append(_Literal(parts[0].start if parts else start, end, _BUILD[operation], parts))
    return [item for item in stack if item is not None and item.kind not in ("scalar", "name") and
            item.end - item.start >= _MIN_LITERAL_BYTES]


def _large_literals(instructions, constants, names):
    run = []
    for instruction in itertools.chain(instructions, (None,)):
        if (instruction is not None and instruction[2] in _LITERAL_OPS and
                (instruction[2] != _CALL or instruction[3] < 256)):
            run.append(instruction)
            continue
        if run and run[-1][1] - run[0][0] >= _MIN_LITERAL_BYTES:
            for literal in _literal_run(run, constants, names):
                yield literal
        run = []


def _jump_target(instruction):
    _, end, operation, operand = instruction
    if operation in opcode.hasjrel:
        return end + operand
    if operation in opcode.hasjabs:
        return operand
    return None


def _pack_operation(operation, operand, width=3):
    low = chr(operation) + struct.pack("<H", operand & 0xffff)
    if width == 6:
        return chr(opcode.EXTENDED_ARG) + struct.pack("<H", operand >> 16) + low
    return low


def _compact_lines(code, relocate):
    output = []
    previous_address = 0
    previous_line = code.co_firstlineno
    for offset, line in dis.findlinestarts(code):
        address = relocate(offset)
        delta = address - previous_address
        line_delta = line - previous_line
        while delta > 255:
            output.append("\xff\x00")
            delta -= 255
        while line_delta > 255:
            output.append(chr(delta) + "\xff")
            line_delta -= 255
            delta = 0
        output.append(chr(delta) + chr(line_delta))
        previous_address = address
        previous_line = line
    return "".join(output)


def _compact_code(code, marker_prefix, replacements):
    constants = [
        _compact_code(value, marker_prefix, replacements) if isinstance(value, types.CodeType) else value
        for value in code.co_consts
    ]
    data, lines = code.co_code, code.co_lnotab
    if len(data) >= _MIN_LITERAL_BYTES:
        instructions = list(_instructions(data))
        jumps = [(instruction, _jump_target(instruction)) for instruction in instructions
                 if instruction[2] in opcode.hasjrel or instruction[2] in opcode.hasjabs]
        targets = sorted(target for _, target in jumps)
        patches = {}
        starts, ends, widths, removed = [], [], [], [0]
        for literal in _large_literals(instructions, constants, code.co_names):
            first_inside = bisect.bisect_right(targets, literal.start)
            if first_inside < len(targets) and targets[first_inside] < literal.end:
                continue
            marker = "%s%d_" % (marker_prefix, len(replacements))
            width = 6 if len(constants) > 65535 else 3
            patches[literal.start] = (literal.end, _pack_operation(_LOAD, len(constants), width))
            starts.append(literal.start)
            ends.append(literal.end)
            widths.append(width)
            removed.append(removed[-1] + literal.end - literal.start - width)
            constants.append(marker)
            replacements[marker] = literal

        if starts:
            def relocate(offset):
                count = bisect.bisect_left(starts, offset)
                if count and offset < ends[count - 1]:
                    return starts[count - 1] + widths[count - 1] - removed[count - 1]
                return offset - removed[count]

            for (start, end, operation, _), target in jumps:
                operand = relocate(target)
                if operation in opcode.hasjrel:
                    operand -= relocate(end)
                patches[start] = (end, _pack_operation(operation, operand, end - start))
            parts, end = [], 0
            for start, (next_end, replacement) in sorted(patches.items()):
                parts.extend((data[end:start], replacement))
                end = next_end
            parts.append(data[end:])
            data = "".join(parts)
            lines = _compact_lines(code, relocate)

    return types.CodeType(
        code.co_argcount, code.co_nlocals, code.co_stacksize, code.co_flags,
        data, tuple(constants), code.co_names, code.co_varnames, code.co_filename,
        code.co_name, code.co_firstlineno, lines, code.co_freevars, code.co_cellvars,
    )


def reduce_literals(code):
    replacements = {}
    prefix = "_nxscript_literal_" + os.urandom(12).encode("hex") + "_"
    compact = _compact_code(code, prefix, replacements)
    return compact if replacements else code, replacements


def expand_literals(source, replacements):
    if not replacements:
        return source
    pattern = r"(?:[bu])?(['\"])(%s)\1" % "|".join(re.escape(marker) for marker in replacements)
    restored = set()

    def substitute(match):
        marker = match.group(2)
        restored.add(marker)
        return replacements[marker].render()

    source = re.sub(pattern, substitute, source)
    if restored != set(replacements):
        raise ValueError("uncompyle6 did not render all large literal expressions")
    return source
