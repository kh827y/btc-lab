"""Validate a Drive development result against the trusted, checked-out base."""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ID = re.compile(r"[a-z0-9][a-z0-9-]{5,63}\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
REF = "refs/btc-sync/candidate"


def git(*args, binary=False):
    return subprocess.check_output(["git", *args], text=not binary)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def allowed(path):
    p = PurePosixPath(path)
    # First deployment: application code, tests and ordinary documentation only.
    return (not any(part.startswith('.') for part in p.parts)
            and p.parts[0] not in {'data', 'venv', 'node_modules', 'tools'}
            and p.name.lower() not in {'agents.md', 'requirements.txt', 'readme.secret.md'}
            and p.suffix.lower() in {'.py', '.md', '.bat'})


def validate(folder, job):
    require(ID.fullmatch(job), 'Invalid job id')
    folder = Path(folder).resolve()
    bundle = folder / f'{job}.bundle'
    marker = folder / f'{job}.ready.json'
    require(bundle.is_file() and marker.is_file(), 'Missing bundle or ready marker')
    require(0 < bundle.stat().st_size <= 25 * 1024 * 1024, 'Bundle size outside initial limit (25 MiB)')
    require(marker.stat().st_size <= 65536, 'Oversized manifest')
    m = json.loads(marker.read_text(encoding='utf-8'))
    require(isinstance(m, dict) and m.get('schema') == 1 and m.get('job_id') == job, 'Invalid manifest')
    base, head, digest = (m.get(k) for k in ('base_sha', 'head_sha', 'sha256'))
    require(all(isinstance(s, str) and SHA.fullmatch(s) for s in (base, head)), 'Invalid commit SHA')
    require(isinstance(digest, str) and DIGEST.fullmatch(digest), 'Invalid SHA-256')
    require(hashlib.sha256(bundle.read_bytes()).hexdigest() == digest, 'Bundle checksum mismatch')
    require(base == git('rev-parse', 'HEAD').strip(), 'Stale base: regenerate from latest source bundle')
    branch = f'refs/heads/dev-{job}'
    require(git('bundle', 'list-heads', str(bundle)).splitlines() == [f'{head} {branch}'], 'Unexpected bundle refs')
    git('bundle', 'verify', str(bundle))
    git('-c', 'protocol.file.allow=always', 'fetch', '--no-tags', str(bundle), f'{branch}:{REF}')
    require(git('rev-parse', REF).strip() == head, 'Candidate SHA mismatch')
    require(git('rev-list', '--parents', '-n', '1', head).split() == [head, base], 'Exactly one non-merge commit from base required')
    paths = [p.decode('utf-8') for p in git('diff', '--no-renames', '--name-only', '-z', base, head, binary=True).split(b'\0') if p]
    require(paths and all(allowed(p) for p in paths), 'Forbidden or empty change set: ' + repr(paths))
    for entry in git('--literal-pathspecs', 'ls-tree', '-r', '-z', head, '--', *paths, binary=True).split(b'\0'):
        if entry:
            require(entry.split(b' ', 1)[0] in {b'100644', b'100755'}, 'Symlink/submodule or nonregular file not allowed')
    git('diff', '--check', base, head)
    print('Validated', job, base, head, paths)
    return m


if __name__ == '__main__':
    validate(sys.argv[1], sys.argv[2])
