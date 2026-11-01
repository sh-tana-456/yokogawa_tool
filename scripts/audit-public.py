#!/usr/bin/env python3
"""Read-only pre-publication audit. Never prints matched secret values."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = {'.git', '.venv', 'build', 'dist', '.pytest_cache', '__pycache__',
           'captures', 'samples', '.aws', '.codex', '.agents', '.ssh', '.gnupg'}
PATTERNS = {
    'private-key': rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----[\r\n]+[A-Za-z0-9+/=\r\n]{40,}-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----',
    'github-token': rb'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})\b',
    'aws-access-key': rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
    'bearer-token': rb'(?i)Bearer\s+[A-Za-z0-9._~+/-]{20,}',
    'home-directory': rb'/(?:home|Users)/[A-Za-z0-9_.-]+/',
}


def credential_path(name):
    path = Path(name)
    return (bool(set(path.parts) & {'.aws', '.codex', '.agents', '.ssh', '.gnupg'})
            or (path.name != '.env.example' and (path.name == '.env' or path.name.startswith('.env.')))
            or path.suffix.lower() in {'.pem', '.key', '.p12', '.pfx'})


def git(*args):
    try:
        result = subprocess.run(['git', '-C', str(ROOT), *args], capture_output=True, check=False)
    except FileNotFoundError:
        return b''
    return result.stdout if result.returncode == 0 else b''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', action='store_true', help='Also inspect current dist archives')
    args = parser.parse_args()
    findings, checked = [], 0

    def scan(name, data, third_party=False):
        nonlocal checked
        checked += 1
        for kind, pattern in PATTERNS.items():
            if third_party and kind == 'home-directory':
                # Upstream binaries may retain upstream build paths. Still
                # detect this workstation's home, without printing its value.
                count = data.count(str(Path.home()).encode()+b'/')
            else:
                count = len(re.findall(pattern, data))
            if count:
                findings.append(dict(file=name, kind=kind, count=count))

    top = git('rev-parse', '--show-toplevel').decode().strip()
    in_git = bool(top) and Path(top).resolve() == ROOT
    if in_git:
        names = git('ls-files', '--cached', '--others', '--exclude-standard', '-z').decode().split('\0')
        paths = [ROOT/n for n in names if n and (ROOT/n).is_file()]
        for path in paths:
            rel = path.relative_to(ROOT)
            if rel.parts[0] in PRIVATE or credential_path(rel):
                findings.append(dict(file=str(rel), kind='private-file-tracked', count=1))
            scan(str(rel), path.read_bytes())
        commits = git('rev-list', '--all').decode().splitlines()
        seen = set()
        for commit in commits:
            scan('git-commit:'+commit[:12], git('cat-file', 'commit', commit))
            for entry in git('ls-tree', '-r', '-z', commit).split(b'\0'):
                if not entry:
                    continue
                header, name = entry.split(b'\t', 1)
                object_id = header.split()[-1]
                if object_id not in seen:
                    seen.add(object_id)
                    if credential_path(name.decode()):
                        findings.append(dict(file='git-history:'+name.decode(), kind='private-file-in-history', count=1))
                    scan('git-history:'+name.decode(), git('cat-file', 'blob', object_id.decode()))
    else:
        commits = []
        paths = [p for p in ROOT.rglob('*') if p.is_file() and not set(p.relative_to(ROOT).parts) & PRIVATE]
        for path in paths:
            if credential_path(path.relative_to(ROOT)):
                findings.append(dict(file=str(path.relative_to(ROOT)), kind='private-file-in-source', count=1))
            scan(str(path.relative_to(ROOT)), path.read_bytes())
    artifacts = []
    if args.artifacts:
        for path in sorted((ROOT/'dist').glob('*')):
            if path.name.endswith('.tar.gz'):
                with tarfile.open(path) as archive:
                    for member in archive:
                        name = member.name
                        if credential_path(name):
                            findings.append(dict(file=path.name+':'+name, kind='credential-file-in-artifact', count=1))
                        if set(Path(name).parts) & (PRIVATE-{'dist', 'build', '.git'}):
                            findings.append(dict(file=path.name+':'+name, kind='private-path-in-artifact', count=1))
                        if member.uname or member.gname or member.uid or member.gid:
                            findings.append(dict(file=path.name+':'+name, kind='archive-owner', count=1))
                        if member.isfile():
                            scan(path.name+':'+name, archive.extractfile(member).read(), '/_internal/' in name)
                artifacts.append(path.name)
            elif path.suffix == '.whl':
                with zipfile.ZipFile(path) as archive:
                    for name in archive.namelist():
                        if credential_path(name):
                            findings.append(dict(file=path.name+':'+name, kind='credential-file-in-artifact', count=1))
                        scan(path.name+':'+name, archive.read(name))
                artifacts.append(path.name)
    print(json.dumps(dict(files_and_objects_checked=checked, git_commits=len(commits),
                          artifacts=artifacts, findings=findings,
                          limitations='Pattern check only. Screenshots, licensing, author identity and arbitrary unknown secrets require separate review.'),
                     ensure_ascii=False, indent=2))
    raise SystemExit(bool(findings))


if __name__ == '__main__':
    main()
