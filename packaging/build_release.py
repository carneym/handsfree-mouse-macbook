"""Build a self-contained Apple silicon app, drag-to-Applications DMG and ZIP.

Run with the project's venv on an Apple silicon Mac. No developer-specific
paths, saved device addresses or calibration profiles are included. Developer
ID signing is optional via --identity; unsigned builds use ad-hoc signatures.
"""
import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys
import zipfile
from verify_release import audit

PROJECT = Path(__file__).resolve().parent.parent
VERSION = '1.4.0'
IDENTIFIER = 'ie.michaelcarney.headmouse'


def run(*args, **kwargs):
    subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def info(app, **values):
    path = app / 'Contents/Info.plist'
    data = plistlib.loads(path.read_bytes())
    data.update(values)
    path.write_bytes(plistlib.dumps(data))


def build(identity=None):
    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        raise SystemExit('Build this release with an arm64 Python on Apple silicon macOS.')
    release = PROJECT / 'release'
    work = PROJECT / 'build/release'
    release.mkdir(exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    dist = work / 'dist'
    common = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed',
              '--onedir', '--target-architecture', 'arm64', '--paths', PROJECT / 'desktop',
              '--distpath', dist, '--workpath', work / 'pyinstaller', '--specpath', work,
              '--icon', PROJECT / 'packaging/HeadMouse.icns']
    if identity:
        common += ['--codesign-identity', identity]
    environment = dict(os.environ, MACOSX_DEPLOYMENT_TARGET='14.0',
                       PYINSTALLER_CONFIG_DIR=str(work / 'cache'))
    for name, entry, bundle_id, extra in (
        ('Head Mouse', 'head_mouse.py', IDENTIFIER,
         ['--add-data', f'{PROJECT / "desktop/assets"}:assets',
          '--hidden-import', 'bleak.backends.corebluetooth.client',
          '--hidden-import', 'bleak.backends.corebluetooth.scanner',
          '--hidden-import', 'pynput.mouse._darwin',
          '--hidden-import', 'pynput.keyboard._darwin', '--hidden-import', 'Quartz']),
        ('Head Mouse Menu', 'menu_entry.py', IDENTIFIER + '.menu', []),
    ):
        run(*(common + ['--name', name, '--osx-bundle-identifier', bundle_id] + extra +
              [PROJECT / 'desktop' / entry]), env=environment)
    app = dist / 'Head Mouse.app'
    menu = dist / 'Head Mouse Menu.app'
    info(menu, CFBundleVersion=VERSION, CFBundleShortVersionString=VERSION,
         LSUIElement=True, LSMinimumSystemVersion='14.0', NSHighResolutionCapable=True)
    helpers = app / 'Contents/Helpers'
    helpers.mkdir(exist_ok=True)
    shutil.move(str(menu), helpers / menu.name)
    info(app, CFBundleVersion=VERSION, CFBundleShortVersionString=VERSION,
         LSMinimumSystemVersion='14.0', NSHighResolutionCapable=True,
         NSBluetoothAlwaysUsageDescription='Connect to your XIAO head mouse to receive motion and click readings.',
         NSBluetoothPeripheralUsageDescription='Connect to your XIAO head mouse.',
         NSHumanReadableCopyright='Head Mouse — personal head-movement pointer tool')
    resources = app / 'Contents/Resources'
    shutil.copy2(PROJECT / 'packaging/INSTALL.txt', resources / 'INSTALL.txt')
    licenses = resources / 'Third Party Notices'
    licenses.mkdir(exist_ok=True)
    versions = {}
    for distribution in metadata.distributions():
        package = distribution.metadata['Name']
        if not package.lower().startswith(('pyobjc', 'pynput', 'pyserial', 'bleak')):
            continue
        versions[package] = distribution.version
        for file in distribution.files or ():
            if (file.name.lower().startswith(('license', 'licence', 'copying', 'copyright'))
                    and file.suffix.lower() in ('', '.txt', '.md', '.rst', '.html', '.lgpl')):
                source = distribution.locate_file(file)
                if source.is_file():
                    shutil.copy2(source, licenses / (package + '-' + source.name))
    for file in (PROJECT / 'packaging/licenses').glob('*.txt'):
        shutil.copy2(file, licenses / file.name)
    import PyInstaller
    versions.update(Python=platform.python_version(), PyInstaller=PyInstaller.__version__)
    (licenses / 'Bundled versions.json').write_text(json.dumps(versions, indent=2) + '\n')
    python_license = Path(sys.base_prefix) / 'lib/python3.14/LICENSE.txt'
    if python_license.is_file():
        shutil.copy2(python_license, licenses / 'Python-LICENSE.txt')
    # Both PyInstaller-built bundles already have individually signed native
    # libraries. Re-sign changed bundles from the inside out, never --deep sign.
    sign = ['codesign', '--force', '--sign', identity or '-']
    if identity:
        sign += ['--options', 'runtime', '--timestamp']
    run(*sign, helpers / 'Head Mouse Menu.app')
    run(*sign, app)
    verification = audit(app)
    (release / 'verification.json').write_text(json.dumps(verification, indent=2) + '\n')
    stage = work / 'Head Mouse Installer'
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    shutil.copytree(app, stage / app.name, symlinks=True)
    (stage / 'Applications').symlink_to('/Applications')
    shutil.copy2(PROJECT / 'packaging/INSTALL.txt', stage / 'Read Me First.txt')
    with zipfile.ZipFile(stage / 'Sources and build instructions.zip', 'w', zipfile.ZIP_DEFLATED) as sources:
        for folder in ('desktop', 'packaging'):
            for file in (PROJECT / folder).rglob('*'):
                if (not file.is_file() or '__pycache__' in file.parts
                        or file.name.startswith('.') or file.suffix in ('.pyc', '.DS_Store')):
                    continue
                if folder == 'desktop' and file.parent != PROJECT / 'desktop' and 'assets' not in file.parts:
                    continue
                sources.write(file, file.relative_to(PROJECT))
        sources.write(PROJECT / 'README.md', 'README.md')
    name = f'Head-Mouse-{VERSION}-Apple-Silicon'
    dmg = release / (name + '.dmg')
    archive = release / (name + '.zip')
    run('hdiutil', 'create', '-volname', 'Head Mouse', '-srcfolder', stage,
        '-ov', '-format', 'UDZO', dmg)
    if archive.exists():
        archive.unlink()
    run('ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', stage, archive)
    shutil.copy2(PROJECT / 'packaging/INSTALL.txt', release / 'INSTALL.txt')
    manifest = dict(version=VERSION, architecture='arm64', minimum_macos='14.0',
                    signing='Developer ID' if identity else 'ad-hoc (not notarized)',
                    sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (dmg, archive)})
    (release / 'release-info.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('App:', app)
    print('Installer:', dmg)
    print('ZIP:', archive)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--identity', help='Developer ID Application signing identity')
    build(parser.parse_args().identity)
