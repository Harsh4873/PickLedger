# Model refresh recovery

GitHub cron can arrive late or be dropped. The model refresh and the freshness
guard used the same scheduler, so adding more cron entries did not give them an
independent clock. A healthy same-day warmup also hid a missed later refresh.

The guard now checks `generatedAt` against the latest scheduled model window:
06:30 and 13:00 America/Chicago. The Daily Refresh coordinator uses the same
timezone-aware schedule, keeping both local times fixed through daylight saving.
It runs models, player props, and external feeds sequentially, then requests
Pages deployment. Individual writers remain manually dispatchable. External feed
updates to `updatedAt` do not count as a model refresh. Core models must also
be healthy and dated for the current Central day.

The lightweight guard runs on its cron, after other data workflows complete,
and when requested by the local Scores24 publisher. The macOS backup clock
requests that same guard every 15 minutes between 06:30 and 19:00 Central.
It requires the Mac to be awake, online, and logged in with an authenticated
`gh`; after sleep, its next execution checks the current window. GitHub Actions
still runs the models, so an Actions outage can delay recovery.

Install or update the local clock from the maintained checkout:

```sh
python3 scripts/automation/install_model_refresh_guard.py
```

The generated launch agent and local paths stay outside the public repository.
Logs are in `~/Library/Logs/PickLedger/`. The installer is safe to rerun.
Remove it with `launchctl bootout gui/$(id -u)/bet.harsh.pickledger.model-refresh-guard`
and delete its plist from `~/Library/LaunchAgents/`.

Every trigger is serialized through `model-cache-freshness-guard`. A queued or
running model refresh or Daily Refresh coordinator prevents another dispatch. Failed or cancelled attempts
have a 20-minute cooldown and at most three manual/recovery attempts per window.
Exhausting recovery fails the guard visibly. The next window resets the budget.
The guard recovers player props only when models are fresh or waiting out a
retry cooldown. It does not queue props behind a pending model run in the
shared `pick-cache-writer` group, where a second pending writer replaces the
first. A model outage therefore need not prevent props recovery during cooldown.
If the current window ran but a core model failed, recovery reruns just the
failed models. A missed window requests the full Daily Refresh coordinator, including props,
CFB/NFL external feeds, and deployment. A healthy same-day morning cache does
not satisfy the afternoon window.

Scores24, tennis, and CFB share an ESPN scoreboard client with three bounded
attempts for temporary failures and invalid JSON. It prefers HTTPS and switches
between ESPN's existing public HTTP/HTTPS endpoints after a 403, since their
edges can behave differently on local and hosted runners. No credentials are
sent with scoreboard requests. Only a valid `events` list can
confirm an off-day; tennis requires responses from both ATP and WTA. If ESPN
remains unavailable, existing cache fallback and optional-feed failure handling
still apply. This avoids publishing a network error as an empty sports slate.

Verification uses the source smoke tests, frontend tests/build, data upcheck,
and Actions job results. A successful Pages workflow is only a deployment when
the `deploy` job itself ran successfully.
