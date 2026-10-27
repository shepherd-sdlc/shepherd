# Updating Shepherd

Claude Code installs and updates Shepherd. Shepherd only tells you which of Claude Code's commands
to run next. Your projects' `.sdlc/` folders (state, specs, ledgers, sign-offs) are never touched by
an update.

## The short way: `/sprd-update`

In Claude Code, run:

```
/sprd-update
```

It refreshes the catalogue Shepherd comes from, says which version you have and which is current,
and offers the one command that moves you forward. It runs that command when you say yes, then checks
again until you are current. Finally it offers to turn on automatic updates, so you never have to do
this again.

`/sprd-update` arrived after 2.1.0. If your Shepherd does not have it yet, use the steps below once.

Update Claude Code itself first (`claude update`). The 1.x migration relies on Claude Code's catalogue
`renames` feature, and Claude Code's documentation names no minimum version for it.

## By starting point

Every command below runs as-is in PowerShell or any other terminal. After any of them, restart
Claude Code or run `/reload-plugins`: a running session keeps the version it loaded.

### From 1.x (your commands are `/sdlc-*`)

Shepherd 1.x was installed as `claude-code-sdlc`. Its catalogue now carries a rename, so refreshing
the catalogue moves you to the new name and one install finishes the move:


```powershell
claude plugin marketplace update mckruz
claude plugin install shepherd@mckruz
```

Then, in each project set up before 2.0, run `/sprd-upgrade`. It renames the `/sdlc-*` commands in
the project's `CLAUDE.md` and brings the delivery harness forward. A hand-adapted harness file is
shown as a conflict, never overwritten. Your habits change only by prefix: `/sdlc-status` is
`/sprd-status`, and so on.

The refresh also rewrites `claude-code-sdlc@mckruz` to `shepherd@mckruz` in the settings files of
the project you are in, including `.claude/settings.json`, which teams commit. Commit that change so
your teammates get it.

If you use the Shepherd desktop app, **update the app first**. A 1.x app cannot find a 2.x plugin,
while a 2.x app finds either.

### From 2.x

```powershell
claude plugin update shepherd@mckruz
```

If it says Shepherd is already at the latest version but you expected a newer one, refresh the
catalogue first with `claude plugin marketplace update mckruz`, then run the update again.


## Automatic updates

Claude Code updates plugins by itself only from catalogues with automatic updates turned on, and they
are off by default for every catalogue that is not Anthropic's. With them on, Claude Code checks the
catalogue after a session starts and installs a new release for the next launch.

To turn them on, say yes when `/sprd-update` offers, or in Claude Code open `/plugin`, choose
**Marketplaces**, the Shepherd catalogue, then **Enable auto-update**.

A catalogue in a private GitHub repository updates in the background only if git can reach GitHub
without asking for a password. If updates never arrive, run this once:

```powershell
gh auth setup-git
```
