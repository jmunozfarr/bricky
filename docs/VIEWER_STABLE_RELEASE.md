# 3D viewer stable-release validation

The dedicated visual builder supports model inspection and authored building instructions on desktop and tablet. Imported source files remain immutable; every scene is a derived, bounded representation selected by API safety metadata. Design rationale and baseline measurements are in [`VISUAL_BUILDER_DESIGN.md`](VISUAL_BUILDER_DESIGN.md).

## Interaction contract

- Pointer: drag to rotate, scroll to zoom, and use OrbitControls secondary gestures to pan.
- Touch: one finger rotates; two fingers zoom and pan.
- Keyboard focus is placed on the viewport. Left/Right changes steps, Home/End selects the first/final step, `R` resets, `F` toggles fullscreen, `1`–`4` selects isometric/front/right/top, and `+`/`-` zooms.
- Build mode shows current parts in full colour with oxblood edges, previous parts ghosted, and future parts hidden. Inspect mode shows the complete safe occurrence.
- Camera position is preserved across steps and refitted when entering a different build task or explicitly choosing a preset/reset.
- System theme is the default. System, light, and dark preferences are available in the application header and stored locally as the non-domain UI preference `bricky-theme`.

## Automated release gates

Run all unit, integration, build, bundle, browser, and accessibility gates through Compose:

```sh
./scripts/check.sh
```

The browser suite can be run independently with `./scripts/e2e.sh`. It uses a pinned test-only Playwright image and covers Chromium desktop, Firefox desktop, WebKit tablet, keyboard step navigation, theme persistence, responsive overflow, and Axe audits. It does not add a production runtime service.

## Moderated usability gate

Recruit three to five participants representing both people following physical building instructions and people inspecting LDraw models. Each participant should complete these tasks without coaching:

1. Orient a model, choose top and isometric views, zoom, reset, and enter/leave fullscreen.
2. Move to a requested step using buttons and keyboard controls.
3. Identify every exact part and inventory shortage at a requested step.
4. Open an attached subassembly task, complete it, then return to the remembered parent step.
5. Switch between Build, As-built and Inspect, then select dark mode and confirm it survives a reload.

Record task completion, assistance, errors, and a 1–7 task-ease score. Stable release requires every critical task to complete without assistance, a median task-ease score of at least 5, no unresolved critical/high-severity usability issue, and retesting of every changed task. This human gate must be signed off manually; automated checks cannot substitute for it.

## Manual compatibility gate

- Verify keyboard-only focus order and visible focus treatment in both themes.
- Verify the dynamic step/status summaries with a screen reader.
- Verify mouse and tablet touch gestures, fullscreen exit/focus return, WebGL-unavailable messaging, and context-loss recovery.
- Capture light and dark screenshots for the release pull request.
