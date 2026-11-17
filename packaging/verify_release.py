"""Audit a relocated macOS bundle for architecture, external links and privacy."""
import json
from pathlib import Path
import plistlib
import subprocess
import sys
from macholib.MachO import MachO
from macholib.mach_o import LC_BUILD_VERSION, LC_VERSION_MIN_MACOSX


def audit(app):
    app = Path(app).resolve()
    count, minima, errors = 0, set(), []
    for path in app.rglob('*'):
        if path.is_symlink():
            if not path.resolve().is_relative_to(app):
                errors.append(f'External symlink: {path.relative_to(app)}')
            continue
        if not path.is_file():
            continue
        if path.name in ('.head_mouse_profile.json', 'profile.json'):
            errors.append('Personal profile included')
        with path.open('rb') as file:
            magic = file.read(4)
        if magic not in (b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xfe\xed\xfa\xcf'):
            continue
        count += 1
        for header in MachO(str(path)).headers:
            if header.header.cputype != 0x0100000C:
                errors.append(f'Non-arm64 binary: {path.relative_to(app)}')
            for load, command, _data in header.commands:
                if load.cmd in (LC_BUILD_VERSION, LC_VERSION_MIN_MACOSX):
                    version = command.minos if load.cmd == LC_BUILD_VERSION else command.version
                    minima.add((version >> 16, (version >> 8) & 255, version & 255))
            for _index, _type, name in header.walkRelocatables():
                if name.startswith('/') and not name.startswith(('/System/Library/', '/usr/lib/')):
                    errors.append(f'External library: {name}')
    declared = plistlib.loads((app / 'Contents/Info.plist').read_bytes())['LSMinimumSystemVersion']
    if max(minima) > tuple(map(int, declared.split('.'))) + (0,):
        errors.append('A bundled native component requires a newer macOS than declared')
    if errors:
        raise SystemExit('\n'.join(errors))
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    return dict(native_files=count, architecture='arm64', minimum_macos=declared,
                external_dependencies=[], external_symlinks=[], personal_profiles=[],
                signature='verified')


if __name__ == '__main__':
    print(json.dumps(audit(sys.argv[1]), indent=2))
