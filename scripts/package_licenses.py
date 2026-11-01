"""Collect native package attribution without copying local author/user settings."""
import ast
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


def run(arguments):
    result = subprocess.run(arguments, env={**os.environ, 'LC_ALL': 'C'},
                            text=True, capture_output=True, check=False, timeout=15)
    return result.stdout.strip() if result.returncode == 0 else ''


def collect_native_licenses(stage, toc):
    stage, toc = Path(stage), Path(toc)
    target = stage/'licenses'
    python_license = Path(sys.base_prefix)/f'lib/python{sys.version_info.major}.{sys.version_info.minor}/LICENSE.txt'
    if python_license.exists():
        (target/'Python').mkdir(exist_ok=True)
        shutil.copyfile(python_license, target/'Python/LICENSE.txt')
    common = Path('/usr/share/common-licenses')
    if common.exists():
        shutil.copytree(common, target/'OS-common', symlinks=False, dirs_exist_ok=True)
    entries = ast.literal_eval(toc.read_text())[0]
    native, packages, missing = [], {}, []
    pacman, dpkg = shutil.which('pacman'), shutil.which('dpkg-query')
    for destination, source, kind in entries:
        if kind not in ('BINARY', 'EXTENSION'):
            continue
        path = Path(source)
        item = dict(file=destination)
        if path.is_relative_to(sys.base_prefix):
            item['origin'] = 'Python runtime'
        elif 'site-packages' in path.parts:
            item['origin'] = 'Python wheel (see package metadata)'
        elif source.startswith(('/usr/lib/', '/lib/')):
            item['origin'] = 'Operating system'
            package = ''
            if pacman:
                package = run([pacman, '-Qoq', source]).split('\n')[0]
            elif dpkg:
                ownership = run([dpkg, '-S', source]) or run([dpkg, '-S', str(path.resolve())])
                if ownership:
                    package = ownership.splitlines()[0].split(': ', 1)[0]
            item['package'] = package or None
            if package and package not in packages:
                details = dict(package=package, copied_notice_files=[])
                if pacman:
                    info = run([pacman, '-Qi', package])
                    for key in ('Version', 'URL', 'Licenses', 'Architecture'):
                        match = re.search(r'^'+key+r'\s*:\s*(.*)$', info, re.M)
                        if match:
                            details[key.lower()] = match[1]
                    license_dir = Path('/usr/share/licenses')/package
                    if license_dir.exists():
                        shutil.copytree(license_dir, target/'OS'/package, symlinks=False, dirs_exist_ok=True)
                        details['copied_notice_files'] = [str(p.relative_to(license_dir)) for p in license_dir.rglob('*') if p.is_file()]
                elif dpkg:
                    details['version'] = run([dpkg, '-W', '-f=${Version}', package])
                    copyright_file = Path('/usr/share/doc')/package.split(':')[0]/'copyright'
                    if copyright_file.exists():
                        folder = target/'OS'/package
                        folder.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(copyright_file, folder/'copyright')
                        details['copied_notice_files'] = ['copyright']
                packages[package] = details
            if not package:
                missing.append(destination)
        else:
            item['origin'] = 'Unclassified'
            missing.append(destination)
        native.append(item)
    report = dict(
        scope='Native components actually collected by PyInstaller; no local source paths or packager identities.',
        redistribution_review_required=True,
        review_note='Attribution collection is not a license clearance. Review exact-version sources, LGPL replacement/relinking requirements, copyright notices, and any package with missing notices before public binary distribution.',
        python_license_copied=python_license.exists(),
        packages=sorted(packages.values(), key=lambda p: p['package']),
        native_files=native, unclassified=sorted(missing),
        packages_without_local_notices=sorted(p for p, info in packages.items() if not info['copied_notice_files']))
    (target/'NATIVE-LIBRARIES.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    (stage/'BINARY-LICENSE-REVIEW.md').write_text(
        '# 同梱バイナリの公開前確認\n\n'
        'アプリ独自コードのMITライセンスは、Python・Qt・OS由来ライブラリへ適用されません。\n'
        '`licenses/NATIVE-LIBRARIES.json` に実際の同梱物と取得できた著作権表記を記録しています。\n'
        '本文・ソース対応・LGPL条件等の確認は未完了です。GitHub Releasesへ公開する前に、\n'
        '`THIRD_PARTY_NOTICES.md` と同梱一覧を確認してください。このファイルは配布許諾の証明ではありません。\n')
    return report
