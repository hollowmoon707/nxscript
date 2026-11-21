"""Build or extract the stock CPython runtime used by standalone nxscript."""

import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from zipfile import ZipFile

BASE_URL = "https://www.python.org/ftp/python/2.7.3/"
SOURCE = "Python-2.7.3.tgz"
WINDOWS_MSI = "python-2.7.3.amd64.msi"
SOURCE_SHA256 = "d4c20f2b5faf95999fd5fecb3f7d32071b0820516224a6d2b72932ab47a1cb8e"
MSI_SHA256 = "71c15bc161d7a97f583badeb8dcfaf31ce92cbea8758faf85eecabfb77454a96"
DECOMPILER = ("uncompyle6==3.2.6", "xdis==3.9.1", "spark-parser==1.8.9", "click==7.1.2")


def upstream_file(work: Path, name: str) -> Path:
    path = work / name
    if not path.is_file():
        with urllib.request.urlopen(BASE_URL + name, timeout=60) as download:
            with path.open("wb") as output:
                shutil.copyfileobj(download, output)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != (SOURCE_SHA256 if name == SOURCE else MSI_SHA256):
        raise ValueError(f"checksum mismatch for {path}")
    return path


def build_linux(work: Path, target: Path) -> Path:
    archive = upstream_file(work, SOURCE)
    with tarfile.open(archive) as source:
        source.extractall(work, filter="data")
    tree = work / "Python-2.7.3"
    math_source = tree / "Modules" / "mathmodule.c"
    # Newer versions of glibc export sinpi, also the name of a private Python helper.
    math_source.write_bytes(re.sub(rb"\bsinpi\b", b"python27_private_sinpi", math_source.read_bytes()))
    cflags = "-O2 -std=gnu11 -fcommon -Wno-error=implicit-function-declaration -Wno-error=incompatible-pointer-types"
    subprocess.run(["./configure", f"--prefix={target}", "--disable-shared"],
                   cwd=tree, env={**os.environ, "CFLAGS": cflags}, check=True)
    subprocess.run(["make", "-j", str(os.cpu_count() or 2)], cwd=tree, check=True)
    subprocess.run(["make", "install"], cwd=tree, check=True)
    shutil.copy2(tree / "LICENSE", target / "LICENSE.txt")
    return target / "bin" / "python2.7"


def extract_windows(work: Path, target: Path) -> Path:
    installer = upstream_file(work, WINDOWS_MSI)
    subprocess.run(
        ["msiexec.exe", "/a", str(installer), "/qn", f"TARGETDIR={target}", "/l*v", str(work / "python-msi.log")],
        check=True,
    )
    return target / "python.exe"


def add_decompiler(work: Path, executable: Path) -> None:
    wheels = work / "wheels"
    subprocess.run(
        [sys.executable, "-m", "pip", "download", "--dest", str(wheels),
         "--python-version", "2.7.3", "--platform", "any",
         "--only-binary", ":all:", "--no-deps", *DECOMPILER],
        check=True,
    )
    site_packages = Path(subprocess.check_output(
        [executable, "-B", "-c", "from distutils.sysconfig import get_python_lib; print(get_python_lib())"],
        text=True,
    ).strip())
    site_packages.mkdir(parents=True, exist_ok=True)
    for wheel in sorted(wheels.glob("*.whl")):
        with ZipFile(wheel) as archive:
            archive.extractall(site_packages)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    work, target = args.work.resolve(), args.target.resolve()
    work.mkdir(parents=True, exist_ok=True)
    if target.exists():
        parser.error(f"runtime destination already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    executable = extract_windows(work, target) if os.name == "nt" else build_linux(work, target)
    if os.name == "nt":
        for file in target.glob("*.msi"):
            file.unlink()
    add_decompiler(work, executable)
    subprocess.run([
        executable, "-B", "-c",
        "import sys, math, uncompyle6; assert sys.version_info[:3] == (2, 7, 3); print(sys.version)",
    ], check=True)


if __name__ == "__main__":
    main()
