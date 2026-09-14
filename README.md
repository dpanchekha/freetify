# Freetify

Freetify is a free, local-first CS2 demo analysis app. It reads `.dem` files on your own computer and provides a lightweight Leetify-style dashboard. No account or cloud upload is required.

## Windows installation

1. Download the project: on GitHub, click **Code → Download ZIP**, then extract it to a folder such as `Documents\Freetify`.
2. Install [Python 3 for Windows](https://www.python.org/downloads/windows/) if needed. During setup, enable **Add Python to PATH**.
3. In the extracted Freetify folder, right-click `install-windows.ps1` and choose **Run with PowerShell**.
4. Use the new **Freetify** shortcut on your desktop to start the app.

If Windows blocks the script, open PowerShell in the Freetify folder and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-windows.ps1
```

The installer creates a local `.venv`, installs the CS2 demo parser, creates a desktop shortcut, and starts the local server at `http://127.0.0.1:8000`.

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
- A signed standalone `.exe` installer

The parser is powered by [`demoparser2`](https://github.com/RPSam/demoparser2). Freetify is currently a functional local analysis foundation, not a complete Leetify replacement.
