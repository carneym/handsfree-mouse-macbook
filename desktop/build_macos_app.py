"""Build a local macOS launcher with a proper Bluetooth usage declaration.

Uses this project's venv and files in place; rebuild after moving the project.
No changes are made to Homebrew's Python.app or macOS permissions.
"""
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import sysconfig
import tempfile


def build():
    if sys.platform != "darwin":
        raise SystemExit("This launcher is for macOS")
    project = Path(__file__).resolve().parent.parent
    bundle = project / "Head Mouse.app"
    macos = bundle / "Contents" / "MacOS"
    macos.mkdir(parents=True, exist_ok=True)
    info = {
        "CFBundleExecutable": "HeadMouse", "CFBundleName": "Head Mouse",
        "CFBundleDisplayName": "Head Mouse", "CFBundleIdentifier": "ie.michaelcarney.headmouse",
        "CFBundlePackageType": "APPL", "CFBundleVersion": "1.1.0",
        "CFBundleShortVersionString": "1.1.0", "NSHighResolutionCapable": True,
        "NSBluetoothAlwaysUsageDescription": "Connect to your XIAO head mouse to receive motion readings.",
    }
    (bundle / "Contents" / "Info.plist").write_bytes(plistlib.dumps(info))
    # JSON string literals are valid C literals for these local UTF-8 paths.
    source = r'''
#include <Python.h>
#include <stdlib.h>
int main(int argc, char **argv) {
    PyConfig config;
    PyConfig_InitPythonConfig(&config);
    PyStatus status;
    status = PyConfig_SetBytesString(&config, &config.program_name, VENV);
    if (PyStatus_Exception(status)) Py_ExitStatusException(status);
    status = PyConfig_SetBytesString(&config, &config.executable, VENV);
    if (PyStatus_Exception(status)) Py_ExitStatusException(status);
    char **args = calloc(argc + 2, sizeof(char*));
    args[0] = VENV;
    args[1] = SCRIPT;
    for (int i = 1; i < argc; ++i) args[i+1] = argv[i];
    status = PyConfig_SetBytesArgv(&config, argc+1, args);
    free(args);
    if (PyStatus_Exception(status)) Py_ExitStatusException(status);
    status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status)) Py_ExitStatusException(status);
    return Py_RunMain();
}
'''
    source = ("#define VENV " + json.dumps(str(project / ".venv/bin/python")) + "\n" +
              "#define SCRIPT " + json.dumps(str(project / "desktop/head_mouse.py")) + "\n" + source)
    with tempfile.TemporaryDirectory() as folder:
        cfile = Path(folder) / "launcher.c"
        cfile.write_text(source)
        libdir = sysconfig.get_config_var("LIBDIR")
        subprocess.run(["cc", str(cfile), "-I" + sysconfig.get_path("include"),
                        "-L" + libdir, "-lpython" + sysconfig.get_python_version(),
                        "-Wl,-rpath," + libdir, "-framework", "Cocoa",
                        "-o", str(macos / "HeadMouse")], check=True)
    helper = bundle / "Contents" / "Helpers" / "Head Mouse Menu.app"
    helper_macos = helper / "Contents" / "MacOS"
    helper_macos.mkdir(parents=True, exist_ok=True)
    shutil.copy2(macos / "HeadMouse", helper_macos / "HeadMouseMenu")
    helper_info = {"CFBundleExecutable": "HeadMouseMenu", "CFBundleName": "Head Mouse Menu",
                   "CFBundleDisplayName": "Head Mouse Menu", "CFBundleIdentifier": "ie.michaelcarney.headmouse.menu",
                   "CFBundlePackageType": "APPL", "CFBundleVersion": "1.0", "LSUIElement": True,
                   "NSHighResolutionCapable": True}
    (helper / "Contents" / "Info.plist").write_bytes(plistlib.dumps(helper_info))
    subprocess.run(["codesign", "--force", "--sign", "-", str(helper)], check=True)
    subprocess.run(["codesign", "--force", "--sign", "-", str(bundle)], check=True)
    print(bundle)


if __name__ == "__main__":
    build()
