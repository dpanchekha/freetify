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

For developer setup, the repository includes `install-windows.ps1` and `start-freetify.bat` for Windows, plus `start-freetify.sh` for macOS/Linux. These launch the same native app window after dependencies are installed. Freetify does not fall back to opening a browser.

Run the dependency-free backend checks with `python -m unittest discover -s tests -v`.

## Using Freetify

Click **Scan for new demos**. Freetify checks common Steam/CS2 demo folders directly and copies found demos into its local app-data library before analyzing them. Use **Settings → Choose folder** if your Steam library is in a custom location. Demos remain on the computer and are never uploaded to a remote service.

To prepare Steam match sync, sign in with Steam in Settings and provide a Steam Web API key, the read-only Game Authentication Code, and a recent `CSGO-...` match-sharing code from CS2. Freetify never asks for or stores your Steam password. The app finds the available share-code sequence, lists the matches, and lets you queue individual replays through Steam/CS2 before scanning the local demo library. Valve may not have every older replay available. Sync credentials are held in memory only.

## Current status

Implemented:

- CS2 demo header and round-event parsing
- Kill, death, and headshot extraction
- Per-player K/D, headshot-rate, damage, utility, flash, and impact summaries
- Match detail pages with scoreboards, kill timelines, and a lightweight event-position viewer
- One-click handoff of stored demos to CS2 for full engine playback when Steam is installed
- Local match-history persistence
- Automatic scanning of common Steam/CS2 demo folders on Windows, macOS, and Linux
- Local demo library under the platform-appropriate Freetify app-data directory
- Secure Steam OpenID sign-in (identity only)
- Transparent Freetify impact score from parsed combat data
- Windows installer script, desktop launcher, and packaged app build
- Native bundle workflow for Windows, macOS, and Linux

Not yet implemented:

- Full 2D map playback with camera controls or round-by-round replay scrubbing
- Aim, economy, positioning heatmaps, and coaching recommendations
- A signed installer (the generated installer is currently unsigned, so Windows SmartScreen may show a warning)
- Automatic Steam account match-history discovery without the required Steam codes

The parser is powered by [`demoparser2`](https://github.com/RPSam/demoparser2). Freetify is a functional native desktop analysis app with local match reports and a lightweight event viewer; it is not yet a complete Leetify replacement.
