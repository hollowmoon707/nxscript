"""Build and smoke-test the native bundled and unbundled release archives."""

import argparse
from importlib.metadata import distribution, version
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import venv
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[2]
WINDOWS = os.name == "nt"
PLATFORM = "windows" if WINDOWS else "ubuntu"
EXE = "nxscript.exe" if WINDOWS else "nxscript"
PY27 = Path("python.exe") if WINDOWS else Path("bin/python2.7")


def run(*args, **kwargs):
    subprocess.run(args, check=True, **kwargs)


def archive(source: Path, destination: Path) -> Path:
    if WINDOWS:
        result = Path(str(destination) + ".zip")
        with ZipFile(result, "w", ZIP_DEFLATED) as output:
            for path in sorted(source.rglob("*")):
                if path.is_file():
                    output.write(path, Path(destination.name) / path.relative_to(source))
        return result
    return Path(shutil.make_archive(str(destination), "gztar", source.parent, source.name))


def smoke_test(command: Path, work: Path, env: dict[str, str]) -> None:
    work.mkdir()
    source = work / "example.py"
    source.write_text("def score(n):\n    return sum(i*i for i in range(n) if i % 2)\n"
                      "answer = score(8)\n", encoding="ascii")
    entries, recovered = work / "entries", work / "recovered"
    run(command, "--version", cwd=work, env=env)
    run(command, "pack", "--in", source, "--path", "nested/example.py", "--out", entries, cwd=work, env=env)
    run(command, "unpack", "--in", entries, "--out", recovered, cwd=work, env=env)
    result = (recovered / "nested/example.py").read_text(encoding="utf-8")
    if "def score(" not in result or "answer = score(8)" not in result:
        raise ValueError("the round trip did not recover the smoke test script")


def docs(destination: Path) -> None:
    shutil.copy2(ROOT / "LICENSE", destination / "LICENSE")
    shutil.copy2(ROOT / "docs" / "releases.md", destination / "README.md")


def bundle_notices(destination: Path) -> None:
    notices = destination / "licenses"
    notices.mkdir()
    python_version = ".".join(map(str, sys.version_info[:3]))
    url = f"https://raw.githubusercontent.com/python/cpython/v{python_version}/LICENSE"
    with urllib.request.urlopen(url, timeout=30) as source:
        (notices / "CPython-3.txt").write_bytes(source.read())
    for package in ("pyinstaller", "rich", "markdown-it-py", "mdurl", "pygments", "mmh3"):
        metadata = distribution(package)
        for item in metadata.files or ():
            if ".dist-info" in item.as_posix() and item.name.upper().startswith(("LICENSE", "COPYING", "NOTICE")):
                target = notices / f"{package}-{item.name}"
                shutil.copy2(metadata.locate_file(item), target)


def test_archive(package: Path, directory: Path) -> Path:
    directory.mkdir()
    shutil.unpack_archive(package, directory)
    (result,) = directory.iterdir()
    return result


def build(work: Path, output: Path, runtime: Path, expected_version: str | None) -> None:
    release_version = version("nxscript")
    if expected_version and expected_version != f"v{release_version}":
        raise ValueError(f"tag {expected_version} does not match package version {release_version}")
    env = {name: value for name, value in os.environ.items()
           if name not in {"NXSCRIPT_PY27", "NXSCRIPT_DECOMPILER_PYTHON", "PYTHONHOME", "PYTHONPATH"}}
    work.mkdir()
    output.mkdir(parents=True, exist_ok=True)
    frozen = work / "frozen"
    sources = ROOT / "src" / "nxscript"
    run(sys.executable, "-m", "PyInstaller", "--onedir", "--noconfirm", "--name", "nxscript",
        "--distpath", frozen, "--workpath", work / "pyinstaller", "--specpath", work,
        "--add-data", f"{sources / '_py27_worker.py'}:nxscript",
        "--add-data", f"{sources / '_literal27.py'}:nxscript", ROOT / "tools/release/launcher.py",
        cwd=work)
    name = f"nxscript-{release_version}-{PLATFORM}-x64"
    bundled = work / f"{name}-bundled"
    (frozen / "nxscript").rename(bundled)
    shutil.copytree(runtime, bundled / "_internal/nxscript/runtime", symlinks=not WINDOWS)
    docs(bundled)
    bundle_notices(bundled)
    bundled_archive = archive(bundled, output / bundled.name)
    extracted = test_archive(bundled_archive, work / "extracted-bundle")
    empty_home = work / "empty-home"
    empty_home.mkdir()
    smoke_test(extracted / EXE, work / "bundled-smoke",
               {**env, "HOME": str(empty_home), "USERPROFILE": str(empty_home)})

    unbundled = work / f"{name}-unbundled"
    unbundled.mkdir()
    run(sys.executable, "-m", "build", "--wheel", "--outdir", unbundled, ROOT, cwd=work)
    docs(unbundled)
    unbundled_archive = archive(unbundled, output / unbundled.name)
    extracted = test_archive(unbundled_archive, work / "extracted-unbundled")
    (wheel,) = extracted.glob("*.whl")
    test_env = work / "wheel-test"
    venv.EnvBuilder(with_pip=True).create(test_env)
    bin_dir = test_env / ("Scripts" if WINDOWS else "bin")
    python = bin_dir / ("python.exe" if WINDOWS else "python")
    run(python, "-m", "pip", "install", wheel, cwd=work, env=env)
    runtime_exe = str(runtime / PY27)
    smoke_test(bin_dir / EXE, work / "unbundled-smoke",
               {**env, "NXSCRIPT_PY27": runtime_exe, "NXSCRIPT_DECOMPILER_PYTHON": runtime_exe})
    print(bundled_archive, unbundled_archive, sep="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tag", help="release tag to verify against the package version")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="nxscript-release-") as temporary:
        build(Path(temporary) / "work", args.out.resolve(), args.runtime.resolve(), args.tag)


if __name__ == "__main__":
    main()
