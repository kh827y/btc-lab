"""Manual Git bridge. Never checkout, merge, force-push or upload the worktree."""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAIN = "https://github.com/kh827y/btc-lab.git"
MAIN_REF = "refs/heads/main"
URL_RE = re.compile(r"https://github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?", re.I)
BRANCH_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,180}")


def git(*args, capture=True, account=None, check=True):
    cmd = ["git", "-c", "credential.useHttpPath=true"]
    if account:
        cmd += ["-c", "credential.username=" + account]
    p = subprocess.run(cmd + list(args), cwd=ROOT, check=check,
                       stdout=subprocess.PIPE if capture else None,
                       text=True, encoding="utf-8", errors="replace")
    return p.stdout.rstrip("\n") if capture else p.returncode


def normalize_url(value):
    m = URL_RE.fullmatch(value.strip())
    if not m:
        raise ValueError("Use an HTTPS GitHub repository URL without credentials.")
    owner, name = m.groups()
    if name in (".", "..") or name.endswith(".lock"):
        raise ValueError("Invalid repository name.")
    return f"https://github.com/{owner}/{name}.git", owner


def check_origin():
    # Inspect both directions, including configured URL rewrites.
    for args in (("remote", "get-url", "--all", "origin"),
                 ("remote", "get-url", "--push", "--all", "origin")):
        urls = git(*args).splitlines()
        if len(urls) != 1:
            raise ValueError("Expected one origin URL.")
        url = urls[0]
        if url in ("git@github.com:kh827y/btc-lab.git", "ssh://git@github.com/kh827y/btc-lab.git"):
            continue
        if normalize_url(url)[0].lower() != MAIN.lower():
            raise ValueError("origin is not the official BTC-Lab repository.")


def last_url():
    if "hoplite" not in git("remote").splitlines():
        return ""
    # Read the literal saved URL, not an arbitrary pushurl.
    return git("config", "--local", "--get", "remote.hoplite.url")


def target_url(value):
    url, owner = normalize_url(value)
    if url.lower() == MAIN.lower() or owner.lower() == "kh827y":
        raise ValueError("The Hoplite target must be a separate account/repository.")
    return url, owner


def fetch_tip(url, ref, account=None):
    git("fetch", "--no-tags", "--no-recurse-submodules", url, ref,
        capture=False, account=account)
    return git("rev-parse", "--verify", "FETCH_HEAD^{commit}")


def push_tip(url, sha, ref, account=None):
    git("push", "--no-follow-tags", "--recurse-submodules=no",
        url, f"{sha}:{ref}", capture=False, account=account)


def remote_tip(url, ref, account=None):
    result = git("ls-remote", "--refs", url, ref, account=account)
    lines = result.splitlines()
    if not lines:
        return None
    if len(lines) != 1 or lines[0].split("\t")[1] != ref:
        raise ValueError("Unexpected remote ref response.")
    return lines[0].split("\t")[0]


def sync():
    saved = last_url()
    print("Current Hoplite repository:", saved or "(not set)")
    entered = input("Paste private repository HTTPS URL, or Enter to keep it: ").strip()
    url, owner = target_url(entered or saved)
    print("Destination:", url)
    if input("Confirm this is your intended PRIVATE Hoplite repository [y/N]: ").strip().lower() != "y":
        raise ValueError("Cancelled.")
    sha = fetch_tip("origin", MAIN_REF)
    print("Official main:", sha)
    # Explicit SHA from remote main, never local HEAD or uncommitted files.
    # Server rejects non-fast-forward updates (including unrelated history).
    push_tip(url, sha, MAIN_REF, owner)
    if remote_tip(url, MAIN_REF, owner) != sha:
        raise ValueError("Remote main did not match the transferred SHA.")
    if saved:
        git("remote", "set-url", "hoplite", url)
    else:
        git("remote", "add", "hoplite", url)
    print("SYNC OK:", sha)
    print("Saved Hoplite URL locally. Tell the agent to use this exact main commit.")


def blocked_path(path):
    p = path.lower()
    name = p.rsplit("/", 1)[-1]
    if p.startswith((".github/", "data/")) or p in (".gitmodules", ".gitattributes"):
        return True
    return (name == ".env" or name.startswith(".env.") or
            name in {"provider_keys.json", "secrets.toml", "credentials.json", "id_rsa", "id_ed25519"}
            or name.endswith((".pem", ".key", ".pfx", ".p12", ".sqlite", ".sqlite3", ".db", ".parquet")))


def import_branch():
    url, owner = target_url(last_url())
    print("Hoplite source:", url)
    branch = input("Exact agent branch (e.g. hoplite/example): ").strip()
    if not BRANCH_RE.fullmatch(branch) or branch in ("main", "master", "HEAD"):
        raise ValueError("Use a separate agent branch, not main/master.")
    git("check-ref-format", "refs/heads/" + branch)
    main = fetch_tip("origin", MAIN_REF)
    head = fetch_tip(url, "refs/heads/" + branch, owner)
    base = git("merge-base", main, head)
    if base == head:
        raise ValueError("No new commits relative to official main.")
    ahead = git("rev-list", "--count", f"{main}..{head}")
    behind = git("rev-list", "--count", f"{head}..{main}")
    # Check paths throughout the incoming commits, including merge-parent diffs,
    # not only the final tree. This is NOT a content/secret scanner.
    paths = git("log", "-m", "--format=", "--name-only", "--no-renames",
                "-z", f"{main}..{head}").split("\0")
    blocked = sorted({p.strip("\n") for p in paths if blocked_path(p.strip("\n"))})
    if blocked:
        print("Blocked paths in incoming history:", *blocked, sep="\n")
        raise ValueError("Sensitive or workflow paths require separate review; nothing pushed.")
    print("Base:", base, "Head:", head, "Ahead:", ahead, "Behind:", behind)
    print(git("log", "--oneline", f"{main}..{head}"))
    print(git("diff", "--no-ext-diff", "--no-textconv", "--stat", base, head))
    # Save the complete incoming commit patches locally, without running agent code.
    out = ROOT / "data" / "hoplite_review"
    out.mkdir(parents=True, exist_ok=True)
    patch = out / (head + ".patch")
    with patch.open("wb") as stream:
        subprocess.run(["git", "log", "--full-history", "-m", "-p", "--binary",
                        "--no-ext-diff", "--no-textconv", f"{main}..{head}"],
                       cwd=ROOT, stdout=stream, check=True)
    dest = "refs/heads/review/hoplite/" + branch
    current = remote_tip("origin", dest)
    if current == head:
        print("ALREADY IMPORTED:", dest, head)
        return
    if current is not None:
        raise ValueError("Review branch already exists with different SHA. Ask ChatGPT before continuing.")
    print("Local patch:", patch)
    print("WARNING: official repository is PUBLIC. All incoming commit contents/history will become public.")
    print("Inspect the patch for secrets/private data before proceeding. Path checks cannot guarantee safety.")
    print("Destination:", dest)
    if input("Type PUBLISH to confirm, or Enter to cancel: ").strip() != "PUBLISH":
        print("Cancelled. Patch retained locally. Nothing pushed.")
        return
    # No force, no checkout, no merge, no main update. Push reviewed SHA only.
    push_tip("origin", head, dest)
    if remote_tip("origin", dest) != head:
        raise ValueError("Imported branch SHA could not be verified.")
    print("IMPORT OK:", dest.removeprefix("refs/heads/"), head)
    print("Send this branch and SHA to ChatGPT for review. Do not run agent code yet.")


def main():
    try:
        check_origin()
        if sys.argv[1:] == ["sync"]:
            sync()
        elif sys.argv[1:] == ["import"]:
            import_branch()
        else:
            raise ValueError("Expected sync or import.")
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError, EOFError, KeyboardInterrupt) as exc:
        print("STOP:", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
