# Roundhouse

A free, local-only CS2 demo dashboard designed for GitHub Pages. It is a lightweight starting point for a Leetify-style experience: match history, simple performance stats, and a Windows-friendly demo folder setting.

## Run it

No build step or installer is required. Open `index.html`, or publish this folder with GitHub Pages. On Windows, use **Choose folder** in Settings and select the folder containing your `.dem` files. Browsers intentionally do not expose arbitrary local paths to a web page, so the picker is required for security.

The UI currently ships with sample match data so the dashboard is useful before the first scan. The selected folder name is stored only in browser local storage. A production analyzer would add a local companion app (or WebAssembly demo parser) to read and parse the selected files.
