# Visual builder design record

## Baseline audit

The July 2026 audit used the local 61-part, nine-step `car.ldr` model. API metadata was not the bottleneck: model detail returned in about 15 ms and playback, occurrence, source, and material requests each returned in 1–5 ms.

The previous frontend created a fresh `LDrawLoader` and cumulative derived source for every step. Traversing the car's nine steps generated approximately 2,094 LDraw requests; individual transitions took 0.4–1.7 seconds in local Chromium. OrbitControls were mounted only after geometry completed and an opaque loading layer intercepted input, explaining the reported initial rotation lock. Camera damping then made successful input feel less direct.

The previous information architecture exposed renderer concepts—hierarchy, local scope, flattened playback, parent/root and reference counts—while omitting the user's primary questions: what is added now, what colour and quantity is required, whether those pieces are owned, and when a subassembly should be built.

## Design decisions

- `/models/{modelId}/build` is a dedicated workspace; model metadata and coverage remain on the detail page.
- Build and Inspect reuse one parsed scene. Build defaults to current parts in full colour with oxblood edges, previous parts ghosted, and future parts hidden. Inspect shows the complete safe occurrence.
- Exact step parts show catalogue and model-wide inventory context. Inventory is never presented as consumed or reserved.
- Subassemblies are user-opened tasks with simple breadcrumbs. Bricky does not invent a global MPD order.
- The technical graph is available only through `?debug=viewer` on model detail.

## Rendering architecture

The builder manifest returns every local step and a stable complete-scene descriptor. Step selection changes visibility and material presentation only; it does not change the scene URL or invoke the loader.

Bounded scenes use a versioned packed LDraw representation. Official parts, subparts, primitives and colour definitions are included as derived MPD files while installed and imported sources remain unchanged. Packing is bounded to 16 MiB and 5,000 dependencies with a 64 MiB process LRU; over-limit or incomplete packs fall back to the existing external library path.

## Acceptance targets

- Builder shell visible within 500 ms.
- Reference car ready within 2 seconds cold and 1 second warm.
- Pointer response within one rendered frame after geometry appears.
- Step transitions under 100 ms with no scene or library requests.
- No pointer-blocking overlay over a usable scene.
- Current-step identity remains available as text and does not depend on colour or opacity alone.

The implementation measured the local packed car at roughly 209 ms to ready, with one scene request and no scene reload when moving to step 2. These figures are diagnostics, not universal device guarantees.
