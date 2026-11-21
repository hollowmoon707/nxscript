import struct

import pytest

from nxscript.errors import ScriptError
from nxscript.opcodes import NEOX_EXTENDED_ARG, STOCK_TO_NEOX, decode_instructions


def arg(opcode, value):
    return bytes([opcode]) + struct.pack("<H", value)


def test_relative_jump_uses_end_of_fused_instruction_and_relocates_lines():
    encoded = arg(0x70, 1) + b"\x14" + bytes([STOCK_TO_NEOX[83]])
    stock, lines = decode_instructions(encoded, b"\x04\x02")
    assert stock == b"\x01" + arg(110, 2) + b"\x01\x01\x53"
    assert lines == b"\x06\x02"


def test_combo_jump_uses_second_operand_and_consumes_continuation():
    encoded = arg(0xA2, 2) + arg(0xB2, 7) + b"\x14" + bytes([STOCK_TO_NEOX[83]])
    stock, lines = decode_instructions(encoded, b"\x03\x01\x04\x02")
    assert stock == arg(107, 2) + arg(114, 8) + b"\x01\x01\x53"
    assert lines == b"\x03\x01\x05\x02"


def test_combo_with_three_operands_and_fixed_operand_fusion():
    encoded = arg(0x7A, 4) + arg(0xB2, 9) + arg(0xB2, 2) + arg(0xAD, 6)
    stock, _ = decode_instructions(encoded, b"")
    assert stock == arg(100, 4) + arg(100, 9) + arg(102, 2) + arg(124, 0) + arg(100, 6)


def test_expansion_can_force_extended_arg_and_change_other_jump_targets():
    encoded = (
        arg(STOCK_TO_NEOX[113], 6)
        + arg(STOCK_TO_NEOX[113], 40006)
        + b"\x14" * 40000
        + bytes([STOCK_TO_NEOX[83]])
    )
    stock, _ = decode_instructions(encoded, b"")
    assert stock[:9] == arg(113, 9) + arg(145, 1) + arg(113, 80009 & 0xFFFF)
    assert stock[80009:] == b"\x53"


def test_prefix_extends_only_the_first_stream_operand():
    encoded = arg(NEOX_EXTENDED_ARG, 1) + arg(0x77, 2) + arg(0xB2, 10)
    stock, _ = decode_instructions(encoded, b"")
    assert stock == arg(145, 1) + arg(100, 2) + arg(100, 10)


@pytest.mark.parametrize("data", [b"\xb2\x00\x00", b"\x7a\x00\x00", b"\x00"])
def test_invalid_instructions_fail(data):
    with pytest.raises(ScriptError):
        decode_instructions(data, b"")
