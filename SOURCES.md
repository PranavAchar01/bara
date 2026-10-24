# Sources

Every part in the Bara catalog comes from a published open-source library. Nothing is
modelled by hand. The enclosure is the only geometry Bara generates itself.

The per-part record (footprint file, each 3D model file, the URL of each at its pinned
commit, licence, placement and the resulting GLB with its bounding box) is in
`server/data/catalog/meshes.json`. The same provenance is carried on every Part in
`server/data/catalog/catalog.jsonl` (SPEC 4.3 `sources`).

## Upstream libraries

| Key | Library | Pinned at | Licence |
|---|---|---|---|
| kicad, kicad3d | KiCad official libraries (symbols, footprints, packages3D), as installed with KiCad 10.0.7. <https://gitlab.com/kicad/libraries> | 10.0.7 | CC-BY-SA-4.0 with the KiCad library exception (<https://www.kicad.org/libraries/license/>) |
| kiswitch | kiswitch keyswitch KiCad library. <https://github.com/kiswitch/kiswitch> | aefcf65038d48d2666ff14530d482be3c350fa6e | MIT OR CC-BY-SA-4.0 (MIT used) |
| marbastlib | marbastlib keyboard KiCad library. <https://github.com/ebastler/marbastlib> | 6b0a9a73f579e377816d60b58eac2b3252de7868 | CERN-OHL-P-2.0 |
| seeed_opl | Seeed Studio OPL KiCad library. <https://github.com/Seeed-Studio/OPL_Kicad_Library> | b0035c51eb0348bb3e165fdb2f2765fa3d1d17bd | CC-BY-SA-4.0 |
| kbd | foostan kbd KiCad library (inside crkbd, `pcbs/common/kbd`). <https://github.com/foostan/crkbd> | 63366fb7f51cf2a796462fdd90527e99dd126055 | MIT |
| crkbd | foostan crkbd (Corne) KiCad boards and plates. <https://github.com/foostan/crkbd> | 63366fb7f51cf2a796462fdd90527e99dd126055 | MIT |
| pmw3360_breakout | jfedor2 PMW3360 breakout (footprint + STEP). <https://github.com/jfedor2/pmw3360-breakout> | 13738eece595fefb1246524429a3c1d3ba7e6ebf | CC0-1.0 |
| klp | KLP Lame keycaps (STEP), by braindefender. <https://github.com/braindefender/KLP-Lame-Keycaps> | 8e4b89b484cafe3bcaced6b459a4e29660991a40 | CC-BY-SA-4.0 |
| dsa | anhthang DSA keycap models (STEP). <https://github.com/anhthang/dsa-keycap> | efc08d0a025057ede925347e8b07d85971778f2b | MIT |
| knobby | quadule knobby knob (STEP, `case/`). <https://github.com/quadule/knobby> | e2f72c0cf8843eea389f30b917bd3db0cc113ffd | MIT |
| flactyl | yangit flactyl shared 3D models (nice!nano STEP). <https://github.com/yangit/flactyl> | e927717dd869d145414e8439c2a5687b8927abc3 | MIT |

Local copies live outside the repo under `~/helloworld/bara-sources/` (shallow clones at
the commits above) and in the KiCad install. Only the converted GLBs are written into
the repo tree.

## Vendor models inside marbastlib

The marbastlib README lists 3D models that were supplied by third parties and are not
covered by the repository licence. Parts using one of those files carry licence
`NOASSERTION` (commercial use unknown) in their record. The list of matched file names
is `MARBASTLIB_VENDOR_MODELS` in `server/catalog_build/resolve.py`.

## Parts without a mesh

Some parts have no licensed 3D model upstream (for example LiPo pouch cells, the TRRS
cable, the trackball ball, and KiCad footprints that ship without a model in 10.0.7).
They stay meshless: their record says `status: "missing"` and the viewer draws the
part's bounding box. A few boards that share a form factor reuse another part's mesh;
those records say `status: "proxy"` and name the part they borrow from.

## How the meshes are made

`server/catalog_build` writes a one-footprint `.kicad_pcb` per part and runs
`kicad-cli pcb export glb`, so KiCad applies each model's own offset, rotation and scale.
Whole boards and plates are exported from the upstream `.kicad_pcb` files. Large GLBs
are simplified with `@gltf-transform/cli` (no Draco or meshopt compression). Output is
glTF metres, Y up; z = 0 is the PCB top face.

Rebuild:

```sh
cd server
uv run --with trimesh --with numpy python -m catalog_build.build check
uv run --with trimesh --with numpy python -m catalog_build.build meshes
uv run --with trimesh --with numpy python -m catalog_build.build parts
```

`parts` writes `catalog.jsonl`, `kicad.jsonl` and `catalog.sqlite` (read through
`server/src/bara/catalog_db.py`).
