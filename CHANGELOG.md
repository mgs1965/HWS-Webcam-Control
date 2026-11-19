#### V49.11.2 - 2026-11-18
- Removed the undeclared pathlib.Path dependency from controller analytics retention.
- Added a defined, defensive dashboard fmtTime() formatter.
- Registered all seven dashboard navigation handlers before optional panel rendering.
- Isolated Controller panel rendering so it cannot disable navigation.
- Added retention execution and JavaScript runtime/navigation verifier gates.
- Normalised malformed release paths in documentation.
- Camera-control behaviour and telemetry-v4 58-field schema remain unchanged.

### V49.11.1 - 2026-11-18
- Fixed controller analytics NameError caused by undefined MIN_FREE_SPACE_GB.
- Added ANALYTICS_MIN_FREE_SPACE_GB = 5.0 as the explicit analytics storage threshold.
- Isolated controller analytics failures from the primary capture cycle.
- Added verifier regression checks for analytics summary creation and capture-cycle isolation.
- Camera-control behaviour and telemetry-v4 58-field schema remain unchanged.

### V49.11 - 2026-11-18
- Combined V49.10 Controller Analytics and V49.11 anomaly intelligence.
- Added 48-hour controller history, limit persistence, per-mode learning and transition events.
- Added configuration fingerprint, per-mode anomaly baselines and explainable camera-health score.
- Extended Controller dashboard with health, persistence, learning, events and anomaly panels.
- Camera-control behaviour and telemetry-v4 58-field schema remain unchanged.

### V49.9.1 - 2026-11-18
- Added a dedicated seventh Controller dashboard view and navigation target.
- Moved detailed controller observability out of the Live Health Checks card.
- Added controller state, learning, limit and current-decision panels.
- Fixed controller rendering to use the embedded D.controller payload.
- Added seven-view and controller-renderer verifier gates.
- Camera control and telemetry-v4 58-field schema remain unchanged.

## Change log

### V49.9 - 2026-11-18
- Fixed the V49.8.0 browser runtime regression caused by the missing `fmt()` dashboard value formatter.
- Restored navigation for 24 Hours, 7 Days, 30 Days, Gallery and Diagnostics.
- Restored rendering of the V49.8 Mode Effectiveness and Mode Separation panels.
- Added verifier assertions for the formatter and all six navigation targets.
- Camera-control behaviour, mode thresholds and telemetry-v4 58-field schema remain unchanged.

### V49.9 - 2026-11-18
- Added Mode Effectiveness analysis using real rolling 24-hour telemetry.
- Added per-mode duration and sample-count cards for DAY, TWILIGHT, LOW LIGHT and NIGHT.
- Added Mode Separation metrics for brightness, exposure, analogue gain and image quality.
- Added observational DISTINCT / REVIEW / NO DATA assessments.
- Added TWILIGHT versus LOW LIGHT evidence summary without changing control behaviour.
- Fixed independent Live and 24 Hours mode timeline render targets.
- Collapsed repeated mode samples into proportional timeline segments with time tooltips.
- Corrected series downsampling to retain the newest point.
- Camera control, thresholds and telemetry-v4 58-field schema remain unchanged.

# Change log
## V49.7.1 - 2026-11-17
- Approved mock-up Live-page geometry is the frozen visual baseline.
- Restored the approved mock-up UI as the dashboard visual source of truth.
- Added persistent operational health strip.
- Added real DAY/TWILIGHT/LOW LIGHT/NIGHT mode timeline from telemetry.
- Added separate diagnostics graphs, log exposure scaling, readable axes/ticks/legends and summary statistics.
- Added telemetry-enriched Gallery cards and filters.
- Renamed Settings to read-only Diagnostics and eliminated raw missing values.
- Preserved V49.5 exact-set Gallery reconciliation and FTP transactional publication.
- Corrected release identity across version, core, documentation and deployment scripts.
- Camera-control behaviour and telemetry-v4 58-field schema unchanged.
