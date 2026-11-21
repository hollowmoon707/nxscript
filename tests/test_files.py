from pathlib import PurePosixPath

import pytest

from nxscript.errors import ScriptError
from nxscript.files import archive_name, output_relative, portable_path, write_output


def test_packed_names_match_archive_mounts():
    assert archive_name(PurePosixPath("sample/nested/example.py")) == "6af011e8.enc"
    assert archive_name(PurePosixPath("lib/example.py")) == "90fa7d73.enc"


def test_output_uses_embedded_tree_or_input_relative_fallback():
    relative = PurePosixPath("_unnamed/in.enc")
    assert output_relative("unpack", relative, b"ui\\module.py") == PurePosixPath("ui/module.py")
    assert output_relative("unpack", relative, b"C:\\elsewhere\\module.py") == PurePosixPath("_unnamed/in.py")


@pytest.mark.parametrize("text", ["../bad.py", "a/../../outside.py", "/rooted.py", "C:drive.py", "dir/CON.py"])
def test_embedded_path_must_be_portable_and_relative(text):
    with pytest.raises(ScriptError):
        portable_path(text)


def test_existing_file_is_kept_until_overwrite(tmp_path):
    target = tmp_path / "dir" / "entry.py"
    assert write_output(target, b"first", overwrite=False)
    assert not write_output(target, b"second", overwrite=False)
    assert target.read_bytes() == b"first"
    assert write_output(target, b"second", overwrite=True)
    assert target.read_bytes() == b"second"
