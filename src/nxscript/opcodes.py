"""Translate NeoX and stock Python 2.7 bytecode inside a marshal payload."""

from bisect import bisect_left
from dataclasses import dataclass

from ._opcode_data import COMBO_FILLER, DIRECT, EXPANSIONS, STOCK_EXTENDED_ARG
from .bytecode import MarshalCode
from .errors import ScriptError

HAVE_ARGUMENT = 0x5A
STOCK_TO_NEOX = {stock: encoded for encoded, stock in DIRECT.items()}
NEOX_EXTENDED_ARG = STOCK_TO_NEOX[STOCK_EXTENDED_ARG]

# CPython 2.7 opcode.hasjabs and opcode.hasjrel.
ABSOLUTE_JUMPS = {111, 112, 113, 114, 115, 119}
RELATIVE_JUMPS = {93, 110, 120, 121, 122, 143}


def _slot(data: bytes, offset: int) -> tuple[int, int, int]:
    opcode = data[offset]
    if opcode < HAVE_ARGUMENT:
        return opcode, 0, offset + 1
    if offset + 3 > len(data):
        raise ScriptError(f"truncated operand at byte {offset}")
    return opcode, data[offset + 1] | data[offset + 2] << 8, offset + 3


def obfuscate(payload: bytes) -> bytes:
    """Apply direct opcode substitution, preserving operands and byte offsets."""
    module = MarshalCode(payload)
    changes = []
    for code in module.codes:
        data = code.instructions.value
        output = bytearray(data)
        offset = 0
        while offset < len(data):
            stock, _, next_offset = _slot(data, offset)
            try:
                output[offset] = STOCK_TO_NEOX[stock]
            except KeyError:
                raise ScriptError(
                    f"{code.name.value!r}: unsupported stock opcode {stock:#04x} at byte {offset}"
                ) from None
            offset = next_offset
        changes.append((code.instructions, bytes(output)))
    return module.replace_strings(changes)


@dataclass
class Instruction:
    opcode: int
    operand: int
    extended: bool = False
    jump_target: int | None = None

    @property
    def width(self) -> int:
        return 1 if self.opcode < HAVE_ARGUMENT else (6 if self.extended else 3)


def _expand(data: bytes):
    """Map NeoX jump targets and line positions to expanded instruction indices."""
    instructions = []
    targets = {}
    line_positions = {}
    offset = 0
    while offset < len(data):
        start = offset
        opcode, operand, offset = _slot(data, offset)
        prefix = None
        while opcode == NEOX_EXTENDED_ARG:
            prefix = (prefix or 0) << 16 | operand
            if prefix > 0x7FFF or offset == len(data):
                raise ScriptError(f"invalid EXTENDED_ARG at byte {start}")
            opcode, operand, offset = _slot(data, offset)
            if opcode < HAVE_ARGUMENT:
                raise ScriptError(f"EXTENDED_ARG before an operand-free instruction at byte {start}")
        if prefix is not None:
            operand |= prefix << 16

        targets[start] = line_positions[start] = len(instructions)
        if opcode in DIRECT:
            entries = ((DIRECT[opcode], "slot", 0),)
            slot_count = int(opcode >= HAVE_ARGUMENT)
        elif opcode in EXPANSIONS:
            slot_count, entries = EXPANSIONS[opcode]
        else:
            raise ScriptError(f"unexpected NeoX opcode {opcode:#04x} at byte {start}")

        operands = [operand]
        continuations = {}
        for slot_index in range(1, slot_count):
            if offset >= len(data) or data[offset] != COMBO_FILLER:
                raise ScriptError(f"missing continuation for opcode {opcode:#04x} at byte {offset}")
            continuations[slot_index] = offset
            _, value, offset = _slot(data, offset)
            operands.append(value)

        for stock, source, value in entries:
            extended = source == "slot" and value == 0 and prefix is not None
            if source == "slot":
                if value in continuations:
                    line_positions[continuations[value]] = len(instructions)
                value = operands[value]
            # Relative operands count from the end of the encoded instruction.
            # The corresponding stock instruction may have a different end.
            target = None
            if stock in RELATIVE_JUMPS:
                target = offset + value
            elif stock in ABSOLUTE_JUMPS:
                target = value
            instructions.append(Instruction(stock, value, extended, target))

    targets[len(data)] = line_positions[len(data)] = len(instructions)
    return instructions, targets, line_positions


def _relocate(instructions: list[Instruction], targets: dict[int, int]) -> list[int]:
    jumps = [(index, instruction) for index, instruction in enumerate(instructions)
             if instruction.jump_target is not None]
    for _, instruction in jumps:
        if instruction.jump_target not in targets:
            raise ScriptError(f"jump target {instruction.jump_target} is outside an instruction boundary")

    # Expansion can make a jump need an EXTENDED_ARG. Lay out again whenever
    # one is added so other jumps see the extra three bytes.
    while True:
        offsets = [0]
        for instruction in instructions:
            offsets.append(offsets[-1] + instruction.width)
        grew = False
        for index, instruction in jumps:
            operand = offsets[targets[instruction.jump_target]]
            if instruction.opcode in RELATIVE_JUMPS:
                operand -= offsets[index + 1]
            if not 0 <= operand <= 0x7FFFFFFF:
                raise ScriptError(f"relocated jump operand {operand} is out of range")
            instruction.operand = operand
            if operand > 65535 and not instruction.extended:
                instruction.extended = True
                grew = True
        if not grew:
            return offsets


def _relocate_lines(lines: bytes, positions: dict[int, int], offsets: list[int]) -> bytes:
    if len(lines) % 2:
        raise ScriptError("odd-length Python 2.7 line table")
    boundaries = sorted(positions)
    previous = encoded = 0
    output = bytearray()
    for addr_delta, line_delta in zip(lines[::2], lines[1::2]):
        encoded += addr_delta
        if not line_delta:
            continue
        # An address inside a multi-byte instruction takes effect at the
        # next traceable instruction; the code end is the final boundary.
        boundary = boundaries[min(bisect_left(boundaries, encoded), len(boundaries) - 1)]
        stock = offsets[positions[boundary]]
        delta = stock - previous
        while delta > 255:
            output.extend((255, 0))
            delta -= 255
        output.extend((delta, line_delta))
        previous = stock
    return bytes(output)


def decode_instructions(data: bytes, lines: bytes) -> tuple[bytes, bytes]:
    instructions, targets, positions = _expand(data)
    offsets = _relocate(instructions, targets)
    output = bytearray()
    for instruction in instructions:
        if instruction.extended:
            output.append(STOCK_EXTENDED_ARG)
            output.extend((instruction.operand >> 16).to_bytes(2, "little"))
        output.append(instruction.opcode)
        if instruction.opcode >= HAVE_ARGUMENT:
            output.extend((instruction.operand & 0xFFFF).to_bytes(2, "little"))
    if len(data) == len(output) and all(offsets[index] == address for address, index in positions.items()):
        return bytes(output), lines
    return bytes(output), _relocate_lines(lines, positions, offsets)


def deobfuscate(payload: bytes) -> bytes:
    """Expand NeoX opcodes in all code objects and relocate their metadata."""
    module = MarshalCode(payload)
    changes = []
    for code in module.codes:
        try:
            data, lines = decode_instructions(code.instructions.value, code.lines.value)
        except ScriptError as exc:
            raise ScriptError(f"{code.name.value!r}: {exc}") from exc
        changes.extend(((code.instructions, data), (code.lines, lines)))
    return module.replace_strings(changes)
