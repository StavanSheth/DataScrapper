# Browser Automation & Lifecycle Guidelines

1. **Strict Extension-Driven In-Window Mode (Zero External Windows / Zero Port 9222):**
   - When the companion Chrome Extension is connected, all automation tabs must be created and automated directly inside the user's active Chrome window via the extension.
   - Never launch secondary Playwright browser contexts or external Chrome processes with `--remote-debugging-port=9222`, which pushes automation into hidden background windows on Windows.

2. **Quiet Tab Execution (`active: false`):**
   - When creating tabs for automation in the user's active window (e.g. Google Maps, Website inspection), always pass `{ active: false }` to `chrome.tabs.create`.
   - Never steal focus away from the user's dashboard tab. Live screencasts (`chrome.debugger`) stream the automation frames to the UI viewports directly.

3. **Continuous Quota Invariant:**
   - In scrapers supporting database deduplication, loop termination conditions must check `len(newly_scraped) >= target_max`, not `(newly_scraped + skipped) >= target_max`.
   - Encountering existing records should trigger fast-forward scrolling without counting toward the target quota.

4. **UI State Protection & Deterministic Synchronization:**
   - Mutating action triggers and scrapers must use bidirectional WebSocket messaging (`START_HARVESTER`, `STATUS`, `LOG`, `JOB_FINISHED`).
   - Prevent UI button flickering by acknowledging state immediately on command dispatch and suppressing conflicting polling overrides.
