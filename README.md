# Light Manager

A Home Assistant integration that moves groups of lights between a **day** and a **night** brightness and color temperature, on a schedule you control.

- Each group has a day setting and a night setting (brightness %, color temperature K).
- Each change *ends* at its target time: sunrise/sunset shifted by ± minutes, or a fixed time of day.
- During the transition (30 minutes by default) the lights fade gradually.
- If you change a light by hand, only that light stops following the schedule. It returns to automatic when you turn it off and on again (configurable per group), or when the next transition starts.
- Lights without color temperature (for example Z-Wave dimmers) get brightness only.

## Install

1. In HACS, open **Custom repositories**, add `https://github.com/ajma/ha-light-manager` with the category **Integration**, then download **Light Manager**.
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration** and add **Light Manager**. It asks no questions.
4. On the Light Manager entry, choose **Add light group**.

## Configure a group

**Step 1:** name, lights, day and night brightness and color temperature, the kind of day and night target (sunrise/sunset or a fixed time), transition length, and what happens when an overridden light is turned off.

**Step 2:** the sunrise/sunset offsets or the fixed times.

To change a group later, choose **Reconfigure** on it:
- **Edit group settings** reopens the two steps.
- **Customize a light** gives one light its own brightness or color temperature. Leave a field blank to follow the group.

Light groups made with the Group helper are expanded into their member lights. A light can belong to only one Light Manager group.

## Entities

| Entity | Global | Per group (e.g. "Living room") |
|---|---|---|
| Automatic switch | `switch.light_manager_automatic` | `switch.living_room_automatic` |
| Day now button | `button.light_manager_day_now` | `button.living_room_day_now` |
| Night now button | `button.light_manager_night_now` | `button.living_room_night_now` |
| Phase sensor | — | `sensor.living_room_phase` |

- **Automatic switches:** a group changes lights automatically only while both the global switch and its own switch are on. Turning automatic back on clears manual overrides and applies the current setting.
- **Day now / Night now:**
  - Applies that setting immediately and holds it until the next transition toward the other setting.
  - A group's buttons work even while it's not automatic.
  - The global buttons act on every group whose own switch is on.
- **Phase sensor:** `day`, `to_night`, `night` or `to_day`. Its attributes are `progress`, `held`, `next_day_target`, `next_night_target` and `overridden_lights`.

## Development

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

## Releasing

Releases are made from GitHub Actions:

1. Go to **Actions → Release → Run workflow** on `main`.
2. Pick **patch**, **minor** or **major**. The manifest starts at `0.0.0`, so pick
   **minor** for the first release (v0.1.0).

The workflow:
1. Fails at once if it wasn't started from `main`.
2. Runs CI.
3. Bumps `version` in `manifest.json` and builds `light_manager.zip` with it.
4. Commits `Release vX.Y.Z` and tags it.
5. Publishes a GitHub release with `light_manager.zip`, which HACS installs.

If the run fails after the tag was pushed, publish the release by hand: build the
zip from `custom_components/light_manager`, then run
`gh release create vX.Y.Z light_manager.zip --verify-tag --generate-notes`.
Or delete the tag and run the workflow again.

Branch protection on `main` that blocks pushes by `GITHUB_TOKEN` also blocks the
release commit.

HACS validation needs the GitHub repository to have a description and topics.
