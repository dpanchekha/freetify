# Freetify

Freetify is a free, local-first CS2 demo analysis app. It reads `.dem` files on your own computer and provides a lightweight Leetify-style dashboard. No account or cloud upload is required.

## Windows installation

The intended user experience is a normal installer: download `FreetifySetup.exe`, run it, and click **Install**. It creates a desktop shortcut and bundles the runtime, so users do not need Python, PowerShell, a ZIP extraction step, or a terminal.

The Windows installer is built automatically by GitHub Actions. To create a Release, push a version tag such as `v1.0.0`:

```bash
git tag v1.0.0
git push origin v1.0.0
```

After the workflow finishes, download `FreetifySetup.exe` from the repository’s **Releases** page. Running the workflow manually creates an Actions artifact but does not publish a Release.

For developer setup, the repository also includes `install-windows.ps1` and `start-freetify.bat`.

## Using Freetify

Open **Settings → Choose folder**, select the folder containing your CS2 `.dem` files, then click **Scan for new demos**. Files are sent only to the local Freetify process, analyzed, and removed from its temporary workspace afterward.

## Current status

Implemented:

- CS2 demo header and round-event parsing
- Kill, death, and headshot extraction
- Per-player K/D and headshot-rate summaries
- Local match-history persistence
- Windows installer script and desktop launcher

Not yet implemented:

- 2D demo viewer or playback
- Detailed match display pages
- Positioning, aim, utility, economy, or coaching analysis
- A signed installer (the generated installer is currently unsigned, so Windows SmartScreen may show a warning)

The parser is powered by [`demoparser2`](https://github.com/RPSam/demoparser2). Freetify is currently a functional local analysis foundation, not a complete Leetify replacement.
