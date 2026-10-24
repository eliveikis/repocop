# Sandboxed Claude sessions

## Problem

Coordinator sessions run unattended with `acceptEdits` and the repository's allowlist. Permission rules match the command text Claude writes, so they aren't a boundary: `bash -c`, an absolute path, or a script the session writes and then runs reaches anything the coordinator's own user can. That includes other repositories' worktrees, the human-owned primary checkouts, credentials under the home directory, the coordinator's own config and database, and on WSL the Windows side: files on the Windows drives and Windows programs. Invariant 1 rests on where a session starts, not on anything that stops it writing elsewhere. The coordinator runs many sessions across unrelated repositories, so one confused or prompt-injected session can do damage far outside its worktree.

## Goal

The operating system confines every command a coordinator session runs. The session writes only inside its worktree and what git needs for it, reaches only the hosts its repository allows, can't read the host's credentials, and on WSL can't reach Windows. It never falls back to running unsandboxed, and on a host that can't sandbox, sessions don't start.

## Depends on

req-1 (v0.1): `services/claude.py`, the task runner, and `make doctor`.

## Requirements

### 1. Every session is sandboxed, by the coordinator

`services/claude.py` turns on Claude Code's sandbox for every session it launches. The coordinator sets it, so nothing in a repository can weaken it:

- **Fail closed.** With `failIfUnavailable`, a sandbox that can't start stops the session, and the task fails with Claude Code's reason. Without it, Claude Code warns and runs commands unsandboxed.
- **No way out.** `allowUnsandboxedCommands` is off, so Claude can't retry a blocked command outside the sandbox, and there are no `excludedCommands`.
- **No prompts for hosts.** With `network.strictAllowlist`, a host outside the allowlist is denied instead of prompted for. Claude Code honours this key only from user, managed or CLI settings, never from a repository's.
- A repository's `.claude/settings.json` can add allowed hosts and denied paths, but can't turn any of the above off.

### 2. Writes

Sandboxed commands can write to the worktree and Claude Code's per-user temp directory. In a linked worktree, Claude Code also allows writes to the primary checkout's shared `.git`, except its `hooks/` and `config`, so `git commit` works. Nothing else is writable: not the primary checkout's files, other worktrees, other repositories, or the home directory. Claude Code's protected paths (the `.claude` settings, skills and hooks, `.git/hooks`, shell startup files) stay read-only inside the worktree too.

File tools aren't sandboxed commands, and they keep following permission rules: `acceptEdits` covers only the worktree, so an edit elsewhere is refused.

### 3. Reads

Sandboxed commands can't read the host's credentials or the coordinator's own state (open question 3 has the list), and on WSL they can't read the Windows drives.

### 4. Network

The allowlist belongs to the repository (open question 2). A command that needs another host fails, and the denial names the host, so the human knows what to add. Claude Code's own traffic to the API isn't a sandboxed command and is unaffected.

### 5. No Windows programs on WSL

On WSL, a Windows program starts through a Unix socket to the Windows host. With the seccomp filter installed and `allowAllUnixSockets` off, sandboxed commands can't reach that socket, so `cmd.exe`, `powershell.exe` and anything on the Windows drives fail however they're invoked. The template's `linux-only-path.sh` hook and `deny` rules stay, for sessions outside the coordinator.

### 6. Host readiness

`make doctor` reports what the sandbox needs on Linux and WSL2: `bubblewrap`, `socat`, the seccomp filter (`@anthropic-ai/sandbox-runtime`, installed with npm), and, on Ubuntu 24.04 and later, whether AppArmor lets `bwrap` create user namespaces. It names each missing piece with the command that installs it.

### 7. Verified, then faked

Before building on it, check with the real CLI in a coordinator worktree (one short run on the subscription, with the user's go-ahead):

- A sandboxed `git commit` succeeds.
- Writes to the primary checkout's files, its `.git/hooks` and `.git/config`, another worktree, and the home directory fail.
- A repository's settings with `sandbox.enabled: false` or `allowUnsandboxedCommands: true` don't take effect.
- A host outside the allowlist is denied without a prompt, and the denial names it.
- Reads of the denied paths fail.
- On WSL, `/mnt/c/Windows/System32/cmd.exe /c ver` fails, and so does reading a file on a Windows drive.
- With `bwrap` missing, the session doesn't start. Note what the SDK reports.
- What a sandbox denial looks like in the message stream.

Record the facts in the "Verified against the real CLI" list in `specs/architecture.md` › Claude Code integration. The fake then reports sandbox denials, and a sandbox that can't start, the same way (`.claude/rules/testing.md`).

## Acceptance Criteria

- The real CLI's sandbox behaviour is verified and recorded in `specs/architecture.md`, and the fake follows it.
- Every session launches with the sandbox on, failing closed, with no unsandboxed retry and no host prompts.
- A repository's settings can't turn the sandbox off or allow unsandboxed commands.
- A sandboxed session in a coordinator worktree can commit its work.
- Writes outside the worktree fail, including to the primary checkout's files, `.git/hooks` and `.git/config`.
- Reads of the denied credential and coordinator paths fail.
- A host outside the repository's allowlist is denied without a prompt, and the denial names the host.
- On WSL, Windows programs can't be started, including by absolute path, and the Windows drives can't be read.
- On a host that can't sandbox, the task fails before Claude runs anything, with the reason.
- `make doctor` names each missing sandbox dependency and how to install it.

## Scope boundaries

Not part of this change:

- Containers or virtual machines per task.
- Sessions a human continues in a terminal with the resume command, and interactive sessions in general. They run with the human's own settings.
- Protecting branch refs in the shared `.git`. Commits need `refs/` to be writable, so a session can still move another branch's ref, including the default branch's. Branch protection on the remote guards what gets merged.
- In-process tools (`Read`, `Edit`, `WebFetch`, `WebSearch`). They stay under permission rules.

## Open questions

Proposed defaults are marked **→**.

1. **How the coordinator passes the settings.** **→** The SDK's `sandbox` option for the keys it types (`enabled`, `allowUnsandboxedCommands`, `network`), and its `settings` option (CLI-level JSON) for the rest: `failIfUnavailable`, `network.strictAllowlist`, and the read denials. To verify: that both arrive as CLI-level settings and win over the repository's.
2. **Where the allowed hosts come from.** **→** The repository's own `.claude/settings.json` (`sandbox.network.allowedDomains`), because what a repository needs depends on its toolchain: PyPI, npm, a private registry. The default template ships an empty list, so a fresh worktree that installs dependencies fails, naming the host, until the repository adds it. The alternative is a coordinator config key with a host-wide default list. It's easier to start with, but every repository gets the union.
3. **Which reads to deny.** **→** A fixed list through `sandbox.credentials` in deny mode, which also unsets secret environment variables: `~/.ssh`, `~/.config/gh`, `~/.aws`, `~/.azure`, `~/.config/gcloud`, `~/.docker/config.json`, `~/.git-credentials` and `~/.netrc`, plus the coordinator's config file and `database_path`. The alternative, `permissions.blockReadsOutsideWorkingDirectories`, is stronger, but probably breaks toolchains that live under the home directory, such as nvm and uv's cache (to verify).
4. **Finding the Windows drives.** **→** Read them from `/proc/mounts` at launch, where WSL2 mounts them as `9p` with `aname=drvfs`. Don't hard-code `/mnt`, because WSL's `[automount] root` setting can move them (invariant 6).
5. **Is the seccomp filter required?** **→** Yes, on every Linux host. Without it the sandbox doesn't block Unix sockets, so on WSL Windows programs still start, and on any host a session could reach the Docker socket or an SSH agent. To verify: whether `failIfUnavailable` covers a missing filter. If it doesn't, the coordinator checks for the filter before launching.
