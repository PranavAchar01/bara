# Board rendering: what Etch does, what Bara does

Notes from reading Etch (`~/helloworld/etch-prod`: `deploy/etch-app/js/board-viewer.js`, `library/render.py`,
`library/optimize.mjs`, `deploy/etch-app/board.html`, `js/editor/main.js`). No Etch code was copied into Bara.

## Etch

- **Source.** Every board is baked offline: `kicad-cli pcb export glb --subst-models --include-tracks --include-pads
  --include-zones --include-silkscreen --include-soldermask`, so the parts are KiCad's own library STEP models,
  placed by KiCad, with footprint nodes named by refdes. gltf-transform then dedups, joins primitives per material,
  welds, quantizes and meshopt-compresses the file. It never simplifies. Each board also gets a raytraced
  `thumb.webp` from `kicad-cli pcb render`.
- **Loading.** A static GLB goes through `GLTFLoader` plus `MeshoptDecoder` (no DRACO). An inline script starts the
  fetch before any module loads, from Cache Storage when it is there. Explore prefetches boards at low priority.
- **First frame.** The KiCad thumbnail is shown first, framed at the same three-quarter angle as the 3D home view
  (25 degrees round, 50 up). The WebGL canvas starts invisible and fades in only after its first real render, while
  the poster fades out. Nothing is drawn before a model exists. A failed load shows a message. There is no timeout
  and no retry.
- **Materials.** KiCad's materials are always replaced. Each one is classified by name, then by colour, into mask,
  silk, pad, copper or body.
  - Mask: physical material, roughness 0.45, clearcoat 0.35/0.3, envMapIntensity 0.6, opacity at least 0.9,
    polygon offset.
  - Silk: roughness 0.85, polygon offset.
  - Pads: ENIG 0xdfb85e, metalness 1, roughness 0.24.
  - Copper under the mask: metalness 0.5, roughness 0.5.
  - FR4: roughness 0.8.
  - Part bodies: keep the STEP colour. Light, unsaturated ones become metal (0.6/0.36), the rest 0.05/0.48.
- **Light.** ACES tone mapping at exposure 1. RoomEnvironment through PMREM, environment intensity 0.55. One
  directional light (1.5) and a hemisphere light (0.7). No shadow maps and no post-processing. Under the board sits
  a fake contact shadow (a blurred rounded rectangle at 0.3 opacity) and a light grid plane. Camera fov is 32, and
  the board fills about 62% of the width and 65% of the height.

## Bara, and how it differs

- **Same source.** Build boards are kicad-cli GLB exports from the board stage. Open-source boards use the same
  baked GLBs Etch publishes (`/explore/glb`, then `etch.chat/world/boards`).
- **One board look for every viewer.** `three/assets.ts` holds the classification and materials, now using Etch's
  values for mask (opacity 0.9 to 0.94, clearcoat 0.35, env 0.6) and ENIG pads. The build view applies it while
  merging meshes per material. The open-source panel (`components/LibraryBoard3D.tsx`) applies it in place through
  `restyleBoardScene`, keeping the scene graph so parts can still be picked by node.
  - Before this change the panel drew the file's raw materials, which made masks pale.
  - A mask opacity capped at 0.85 let copper pours turn keyboards gold.
- **Colour space.** Bara converts board-layer colours back from sRGB for every board GLB. Etch converts only when
  the file's generator says KiCad, but its optimizer rewrites the generator to "Etch". So on Etch some masks come
  out paler than KiCad's own render: Tiny Tapeout shows light blue where the KiCad render is deep blue/purple.
  Bara matches the KiCad render.
- **First frame, open-source panel.** Same idea as Etch. The KiCad poster shows at full strength from the same
  25/50 degree angle (`three/boardView.ts`), and the canvas fades in after two drawn frames.
  - While loading, a small "Opening in 3D" chip shows over the poster, never a bare "Loading".
  - The GLB bytes are cached for the session, with a 30 s timeout and two automatic retries, like build models.
  - A board that still fails keeps its poster and gets a Retry chip.
  - `prefetchBoard(slug)` is exported for the card list to call on hover.
- **First frame, build view.** There is no poster for a board that was just routed, so the board is drawn from its
  record instead (outline, mask over FR4, courtyards in silk). The "Loading 3D board" pill shows only once a load
  has taken more than 1.5 s, so a quick load goes straight from the drawn board to the real one. Companion boards
  draw the same placeholder instead of a gap. The 30 s timeout, two retries and Retry pill (5e7cd6f) are unchanged.
- **Light.** The build view keeps Bara's studio environment, floor and post-processing. The open-source panel uses
  Etch's recipe: ACES, room environment at 0.55, directional 1.5 plus hemisphere 0.7, and a soft contact shadow.
