# Freetify

Freetify is a free, local-first desktop CS2 demo analysis app. It reads `.dem` files on your own computer and provides a lightweight Leetify-style dashboard. No account or cloud upload is required.

## Windows installation

The intended user experience is a normal Windows desktop app: download `FreetifySetup.exe`, run it, and click **Install**. It creates a desktop shortcut and bundles the runtime, so users do not need Python, PowerShell, a ZIP extraction step, a terminal, or a separate browser. Freetify opens in its own application window.

The Windows installer is built automatically by GitHub Actions. From this repository’s `master` branch, publish the current app with:

```bash
git add .
git commit -m "Build Freetify desktop release"
git push origin master
git tag v1.0.4
git push origin v1.0.4
```

Use a new version tag for each release; tags already used in this repository include `v1.0.0` through `v1.0.3`.

After the workflow finishes, download `FreetifySetup.exe` from the repository’s **Releases** page. Running the workflow manually creates an Actions artifact but does not publish a Release.

The repository also builds native desktop bundles for Linux and macOS. Those are currently developer artifacts; Windows is the first platform with a user-facing installer.

For developer setup on macOS/Linux, run `./setup.sh` once. It creates `.venv` and installs `requirements.txt` (including pywebview’s Qt backend on Linux); then run `./start-freetify.sh`. The launcher detaches the app and writes server output to `freetify.log`. Windows developers can use `install-windows.ps1` and `start-freetify.bat`. These launch the same native app window after dependencies are installed, without a console window in the packaged/Windows launcher builds. Freetify does not fall back to opening a browser.

Run the dependency-free backend checks with `python -m unittest discover -s tests -v`.

## Using Freetify

Click **Scan for new demos**. Freetify checks common Steam/CS2 demo folders directly and copies found demos into its local app-data library before analyzing them. Use **Settings → Choose folder** if your Steam library is in a custom location. Demos remain on the computer and are never uploaded to a remote service.

For the recommended CS2 match-history connection, click **Connect CS2** in Settings, scan the QR code with the official Steam mobile app, and approve the request. Freetify stores the resulting Steam client refresh token only in its local app-data state file so it can reconnect after restart; it never asks for your Steam password or uploads the token. Once CS2’s Game Coordinator is ready, click **Sync matches** to retrieve your recent match list.

The older **CS2 match sync** fields below it remain as a fallback for users who already have a Steam Web API key, Game Authentication Code, and `CSGO-...` sharing code. That legacy Valve endpoint can reject otherwise valid credentials with HTTP 412, so the QR/Game Coordinator route is preferred.

## Current status

Implemented:

- CS2 demo header and round-event parsing
- Kill, death, and headshot extraction
- Per-player K/D, headshot-rate, damage, utility, flash, and impact summaries
- Match detail pages with a full scoreboard table and high-fidelity, radar-backed movement playback
- One-click handoff of stored demos to CS2 for full engine playback when Steam is installed
- Local match-history persistence
- Automatic scanning of common Steam/CS2 demo folders on Windows, macOS, and Linux
- Local demo library under the platform-appropriate Freetify app-data directory
- Secure Steam OpenID sign-in (identity only)
- Steam QR approval and local CS2 Game Coordinator connection for recent-match discovery
- Impact Score tracked as K/D × ADR, where ADR is damage per round
- Windows installer script, desktop launcher, and packaged app build
- Native bundle workflow for Windows, macOS, and Linux

The bundled radar assets cover Cache, Mirage, Dust II, Inferno, Nuke, Ancient, Anubis, Overpass, Vertigo, and Train. Their coordinate data and radar artwork are extracted from the Valve game depot; the bundled catalog records their source.

Not yet implemented:

- Multi-level floor selection for Nuke, Vertigo, and Train; round filters; and camera controls
- Aim duels, economy, positioning heatmaps, grenade trajectories, and coaching recommendations
- A signed installer (the generated installer is currently unsigned, so Windows SmartScreen may show a warning)
- Automatic replay-download URLs from every returned CS2 match (CS2 availability varies and this is still being wired into the local demo library)

The parser is powered by [`LaihoE/demoparser`](https://github.com/LaihoE/demoparser) through its `demoparser2` Python package. Freetify is a functional native desktop analysis app with local match reports and a lightweight event viewer; it is not yet a complete Leetify replacement.
