"""Builds dist/RPGMT/RPGMT.exe.  Usage:  .venv\Scripts\python build_exe.py [output folder]

Python 3.10.0's `dis` module crashes on some modern bytecode (fixed in 3.10.1);
guard it during the build so PyInstaller can analyse every package.
"""
import dis
import pathlib
import re
import sys

_orig = dis._get_const_info


def _safe_const_info(*args):
    try:
        return _orig(*args)
    except IndexError:
        return None, ""


dis._get_const_info = _safe_const_info

import PyInstaller.__main__  # noqa: E402

VERSION = re.search(r'__version__ = "([^"]+)"', pathlib.Path("rpgmt/__init__.py").read_text("utf-8")).group(1)
NUMBERS = tuple(int(x) for x in (VERSION.split(".") + ["0"] * 4)[:4])

# Shown in RPGMT.exe > Properties > Details.
VERSION_FILE = pathlib.Path("build/version_info.txt")
VERSION_FILE.parent.mkdir(exist_ok=True)
VERSION_FILE.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={NUMBERS}, prodvers={NUMBERS}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('ProductName', 'RPGMT'),
      StringStruct('FileDescription', 'RPGMT - Reading lobby for RPG Maker games'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('ProductVersion', '{VERSION}'),
      StringStruct('OriginalFilename', 'RPGMT.exe'),
      StringStruct('InternalName', 'RPGMT')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""", "utf-8")

PyInstaller.__main__.run([
    "--noconfirm", "--clean", "--windowed", "--name", "RPGMT",
    "--distpath", sys.argv[1] if len(sys.argv) > 1 else "dist",
    "--version-file", str(VERSION_FILE),
    "--icon", "rpgmt/assets/rpgmt.ico",
    "--add-data", "rpgmt/web;rpgmt/web",
    "--add-data", "rpgmt/assets;rpgmt/assets",
    "--collect-submodules", "winrt", "--collect-binaries", "winrt",
    "--collect-all", "aiortc", "--collect-all", "av", "--collect-all", "pylibsrtp",
    "--collect-all", "aioice", "--collect-all", "webview", "--collect-all", "windows_capture",
    "--hidden-import", "comtypes.stream",
    "--exclude-module", "setuptools", "--exclude-module", "pkg_resources",
    "--exclude-module", "numpy.distutils", "--exclude-module", "distutils",
    # OpenCV only comes along as a windows_capture dependency RPGMT doesn't use (see wincap.py).
    "--exclude-module", "cv2",
    "RPGMT.py",
])
