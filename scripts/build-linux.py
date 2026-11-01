#!/usr/bin/env python3
"""Build a Linux onedir release. Run through uv's locked packaging group."""
import hashlib
from datetime import datetime, timezone
import importlib.metadata as metadata
import json
import platform
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
from package_licenses import collect_native_licenses

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ('numpy', 'PySide6', 'PySide6-Essentials', 'PySide6-Addons',
           'PySide6-Pdf', 'PySide6-WebEngine', 'shiboken6', 'pyqtgraph', 'colorama', 'PyInstaller')


def copy_public_tree(folder, destination):
    """Honor Git's public file set; use a closed file-type set in source exports."""
    result = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', '--show-toplevel'],
                            capture_output=True, text=True, check=False) if shutil.which('git') else None
    in_git = result and result.returncode == 0 and Path(result.stdout.strip()).resolve() == ROOT
    if in_git:
        names = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '--cached',
                                         '--others', '--exclude-standard', '-z', '--', folder]).decode().split('\0')
        files = [ROOT/name for name in names if name and (ROOT/name).is_file()]
    else:
        files = [p for p in (ROOT/folder).rglob('*') if p.is_file()]
    allowed = {'src': {'.py'}, 'scripts': {'.py', '.sh'}, 'tests': {'.py'},
               'docs': {'.md', '.json', '.png'}, 'packaging': {'.py', '.md', '.txt'}}[folder]
    for file in files:
        if folder == 'docs' and (file.name.endswith(('-verification.json', '-benchmark.json'))
                                or file.name in {'publication-audit.json', 'publication.md', 'ToDo.md',
                                                 'display-investigation.md', 'development-history.md'}):
            continue
        if set(file.relative_to(ROOT).parts) & {'.aws', '.codex', '.agents', '.ssh', '.gnupg', '__pycache__', 'captures', 'samples'} or file.name.startswith('.env'):
            continue
        if file.is_symlink():
            raise ValueError(f'Public source symlinks are not supported: {file.relative_to(ROOT)}')
        if file.suffix not in allowed and not (folder == 'packaging' and file.name == 'Dockerfile'):
            continue
        target = destination/file.relative_to(ROOT/folder)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(file, target)


def main():
    if sys.platform != 'linux':
        raise SystemExit('Linux上で実行してください。OS・CPUごとにビルドが必要です。')
    subprocess.run([sys.executable, str(ROOT/'scripts/audit-public.py')], cwd=ROOT, check=True)
    try:
        builder_version = metadata.version('pyinstaller')
    except metadata.PackageNotFoundError:
        raise SystemExit('uv run --locked --no-dev --group packaging python scripts/build-linux.py で実行してください。')
    version = tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['version']
    name = f'yokogawa-tool-{version}-linux-{platform.machine()}'
    work, output = ROOT/'build/linux-package', ROOT/'dist'
    work.mkdir(parents=True, exist_ok=True)
    output.mkdir(exist_ok=True)
    command = [sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm', '--onedir',
               '--name', 'yokogawa-tool', '--paths', str(ROOT/'src'),
               '--distpath', str(work/'frozen'), '--workpath', str(work/'analysis'),
               '--specpath', str(work)]
    for package in RUNTIME:
        command += ['--copy-metadata', package]
    for module in ('PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
                   'PySide6.QtWebEngineQuick', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
                   'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuickWidgets'):
        command += ['--exclude-module', module]
    command += ['--collect-data', 'pyqtgraph', str(ROOT/'packaging/frozen_entry.py')]
    subprocess.run(command, cwd=ROOT, check=True)
    stage = work/'release'/name
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(work/'frozen/yokogawa-tool', stage, symlinks=True)
    copy_public_tree('docs', stage/'docs')
    shutil.copy(ROOT/'readme.md', stage/'readme.md')
    # Keep the documented source links and offline rebuild references usable.
    for folder in ('src', 'scripts', 'packaging', 'tests'):
        copy_public_tree(folder, stage/folder)
    for file in ('pyproject.toml', 'uv.lock', '.dockerignore', 'LICENSE', 'THIRD_PARTY_NOTICES.md'):
        shutil.copy(ROOT/file, stage/file)
    (stage/'demo').mkdir()
    shutil.copy(ROOT/'demo/README.md', stage/'demo/README.md')
    for index in range(6):
        for suffix in ('HDR', 'WVF'):
            shutil.copy(ROOT/f'demo/{index:04}.{suffix}', stage/'demo')
    launcher = stage/'run.sh'
    launcher.write_text('#!/usr/bin/env bash\nset -euo pipefail\n'
                        'bundle_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"\n'
                        'exec "$bundle_dir/yokogawa-tool" "$@"\n')
    launcher.chmod(0o755)
    shutil.copy(ROOT/'packaging/README-Linux.md', stage/'README-FIRST.md')
    # Record dependency metadata and wheel-provided license files. Shared Qt
    # library license texts are supplied separately under packaging/licenses/.
    licenses = stage/'licenses'
    licenses.mkdir()
    license_source = ROOT/'packaging/licenses'
    if license_source.exists():
        shutil.copytree(license_source, licenses/'Qt', dirs_exist_ok=True)
    for name in RUNTIME:
        distribution = metadata.distribution(name)
        folder = licenses/name
        folder.mkdir()
        (folder/'METADATA.txt').write_text(distribution.read_text('METADATA') or '')
        for file in distribution.files or ():
            text = str(file)
            if '.dist-info/' in text and any(s in text.lower() for s in ('license', 'copying', 'notice')):
                target = folder/Path(text.split('.dist-info/', 1)[1])
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(distribution.locate_file(file), target)
    native_licenses = collect_native_licenses(stage, work/'analysis/yokogawa-tool/COLLECT-00.toc')
    versions = {d.metadata['Name']: d.version for d in metadata.distributions()}
    # Inspect actual ELF version strings as a compatibility diagnostic, rather
    # than claiming that every distribution can execute a build from this host.
    glibc = {}
    for file in stage.rglob('*'):
        if file.is_file() and not file.is_symlink():
            with file.open('rb') as stream:
                if stream.read(4) != b'\x7fELF':
                    continue
                symbols = re.findall(rb'\bGLIBC_(\d+\.\d+(?:\.\d+)?)\b', stream.read())
            if symbols:
                glibc[str(file.relative_to(stage))] = max(
                    (s.decode() for s in symbols), key=lambda v: tuple(map(int, v.split('.'))))
    source = hashlib.sha256()
    for file in sorted((ROOT/'src').rglob('*.py')):
        source.update(str(file.relative_to(ROOT)).encode())
        source.update(file.read_bytes())
    manifest = dict(application_version=version, built_at_utc=datetime.now(timezone.utc).isoformat(),
                    source_sha256=source.hexdigest(), platform=platform.platform(),
                    architecture=platform.machine(), build_libc=platform.libc_ver(),
                    python=sys.version, pyinstaller=builder_version, packages=versions,
                    uv_lock_sha256=hashlib.sha256((ROOT/'uv.lock').read_bytes()).hexdigest(),
                    highest_glibc_symbol=max(glibc.values(), key=lambda v: tuple(map(int, v.split('.'))), default=None),
                    glibc_symbols_by_file=glibc,
                    binary_license_review_required=native_licenses['redistribution_review_required'],
                    validation='Not automatically validated on another Linux distribution. Run --package-self-test on the destination.',
                    optional_dependency='sigrok-cli and libsigrokdecode are external and not bundled')
    (stage/'BUILD-INFO.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    archive = output/f'{stage.name}.tar.gz'
    def public_metadata(info):
        info.uid = info.gid = 0
        info.uname = info.gname = ''
        info.mtime = 0
        return info
    # Readers should see either the previous complete package or the new one.
    temporary_archive = archive.with_name(archive.name+'.tmp')
    try:
        with tarfile.open(temporary_archive, 'w:gz') as package:
            package.add(stage, arcname=stage.name, filter=public_metadata)
        temporary_archive.replace(archive)
    finally:
        temporary_archive.unlink(missing_ok=True)
    checksum = archive.with_name(archive.name+'.sha256')
    checksum.write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n')
    print(json.dumps(dict(archive=str(archive), checksum=str(checksum),
                          size_mib=round(archive.stat().st_size/1024**2, 1),
                          build_libc=manifest['build_libc'],
                          highest_glibc_symbol=manifest['highest_glibc_symbol']), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
