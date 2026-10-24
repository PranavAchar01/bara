# Shell sources (verified via GitHub tree listings, 2026-10-24)

Each candidate's `.kicad_pcb` and enclosure paths were confirmed in the repo tree (`git/trees/HEAD?recursive=1`). Component 3D models (libs, parts) were excluded. `fit`: exact = device-class match; close = same size/class; weak = partial; pcb-only = no shell. KiCad version is the file-format code from the PCB header (9 = KiCad 9; 20260206 = KiCad 10 development format). Last commit = GitHub pushed_at. Outer sizes are not in the trees; read READMEs/STEPs when needed. Licence 'none stated' means no LICENSE: do not redistribute without asking.

| Device | Best candidate | Licence | PCB | Shell | Fit | Fallback |
|---|---|---|---|---|---|---|
| video game controller | CoretechR/DIY-Portrait-Mode-Gamepad | GPL-3.0 | `PCB/USB-C Gamepad/Gamepad.kicad_pcb` | STL+STEP (yes: top shell, bottom shell, ) | exact |  |
| monitor with stand | v-cu/dpf-load-monitor-wide | none stated (GitHub: NOASSERTION) | `hardware/kicad/esp32p4amoled3.19.kicad_pcb` | STEP+3MF (not verified) | weak | No repo ships a monitor+stand shell with a KiCad display driver. Borrow a flat b |
| wireless gaming mouse | lambdakb/trackball-lt6c | CERN-OHL-S-2.0 | `pcb/lt6c-pcb.kicad_pcb` | STL+STEP+3MF (yes: top, bottom, shroud) | close | Ploopy upstream (ploopyco/classic-2-trackball, nano-2-trackball, adept-trackball |
| mp3 player | mikeysklar/eink-audio-player | MIT-0 | `kicad/eink-audio-player.kicad_pcb` | FCStd+STEP+STL (yes: bezel, chassis, cradle, d) | exact |  |
| mp4 video player | niyikes/eiko-cam | none stated | `PCB/eiko.kicad_pcb` | STEP+F3D (yes: body, top plate) | weak | No video-player-specific repo found. Borrow mikeysklar/eink-audio-player shell ( |
| flip phone | JeremyLakeyJr/mesh-phone | none stated | `hardware/rev-f/mesh-phone.kicad_pcb (main); hardware/handset` | STL+OpenSCAD (yes: front, rear, pod, port co) | close | No flip phone exists. For the clamshell geometry borrow the two-part clamshell i |
| game boy | codetiger/GameTiger | MIT | `PCB/GameTiger/GameTiger.kicad_pcb` | STL (yes: front, back, buttons) | close | No true DMG-01 reproduction with both a KiCad PCB and a shell was found (Gekkio/ |
| calculator | hotwolf/AriCalculator | GPL-3.0 | `Hardware/RevC/PCB/KiCad/AriCalculator-RevC.kicad_pcb` | STL+OpenSCAD (single case file, likely 2 par) | exact | If AriCalculator is unsuitable, use a keypad handheld shell: acidvegas/t9kb case |
| flashlight | Small-doge128/Gilbert-the-flashlight | none stated | `Gilbert the flashlight ki cad/Gilbert the flashlight.kicad_p` | STEP+STL (single body) | exact |  |
| handheld GPS tracker | felixwittwer/undercity_gps_thingy | GPL-3.0 | `schematics/gps_thingy_schematics/gps_thingy_schematics.kicad` | STL+STEP+3MF (yes: top, middle, bottom, beze) | exact |  |
| USB microphone | mkvenkit/mico | MIT | `pcb/ver0.1/mico.kicad_pcb` | STEP (board) (n/a) | pcb-only | No repo with a shell. Closest same-size shell: Small-doge128/Gilbert-the-flashli |
| power strip with USB | none | | | | none | Nothing found. Closest box: JGAguado/Smart_Plant Enclosure/FDM (Smart-Plant Enclosure Top/Bottom .stl/.stp, licence NOASSERTION, KiCad file  |
| USB-C charger | mikesmitty/power-manifold | MIT | `hardware/backplane/backplane.kicad_pcb (7 boards)` | STEP (partial: side plate and board ) | weak | No wall-charger shell exists. Borrow a small two-part box: JGAguado/Smart_Plant  |
| USB-C power brick | MidwestMotorBoy/Battery-Bank | none stated (NOASSERTION) | `hardware/Production/Monolith.kicad_pcb` | STL (yes: cup, cap, carrier, bumper) | close | For a rectangular brick use JGAguado/Smart_Plant enclosure. |
| Steam Deck-style handheld | ashkan89/esp32-emu-turbo | none stated | `hardware/kicad/esp32-emu-turbo.kicad_pcb` | STL (yes: top, bottom, face buttons) | close |  |
| music synthesizer | JH-2108/Custom-Audio-Synthesizer | none stated | `PCB/Audio Synthesizer.kicad_pcb` | STL+STEP (case + keys) | exact |  |
| smartwatch | Bellafaire/ESP32-Smart-Watch | MIT | `SmartWatch V5/SmartWatch V5.kicad_pcb (V3, V4 also)` | STL+FCStd+STEP (yes: top, bottom) | exact |  |
| fitness band | ljbudgie/openhear | Apache-2.0 | `hardware/wristband/kicad/wristband_v1.kicad_pcb` | STL+OpenSCAD (yes: case, lid) | close | Open-Muscle/OpenMuscle-Band has only trivial STLs. Secondary: Bellafaire watch c |
| smart glasses | Mentra-Community/OpenSourceSmartGlasses | none stated | `electronics_and_firmware/OSSG_v0p1_and_v0p2/pcb/ver0.2/main_` | STEP+STL (frame + temples) | exact |  |
| smart water bottle | barrettotte/goto-bed | MIT | `eda/goto-bed/goto-bed.kicad_pcb` | STL+F3D (yes: top, bottom) | close | Use MidwestMotorBoy/Battery-Bank cylindrical cup/cap for a bottle-cap form. |
| TV / large display | none | | | | none | Nothing found. Display-with-enclosure shells at small scale: v-cu/dpf-load-monitor-wide (enclosure/main_enclosure.step), slomkowski/octoglow |
| TV remote | OMOTE-Community/OMOTE-Hardware | GPL-3.0 | `PCB/Omote.kicad_pcb` | STL+STEP (yes: case, cover plate, button) | exact |  |
| speakers | none | | | | none | No repo has a speaker shell plus KiCad PCB. 74kumi/Esp32-Poe-HA-Speaker (NOASSERTION, hardware/PoE-Speaker/RevE/KiCad-RevE/PoE-Speaker-RevE. |
| smart home speaker | none | | | | none | iMike78/nest-mini-drop-in-pcb (CERN-OHL-S-2.0, nest-mini-v2-drop-in-pcb.kicad_pcb, 618 stars, pushed 2026-10-20) has a PCB for the Google Ne |
| Raspberry Pi Game Boy | jackw01/pi-tin | CERN-OHL-W-2.0 | `pcb_main_r2/mintypcb.kicad_pcb; pcb_display_r2a/displaypcb.k` | STEP (clamshell, 2 parts) | exact |  |
| GameCube-style console | none | | | | none | Nothing found. hackclub/hackxpansion (GPL-3.0, KiCad file format 20260206) is a modular game console but ships board STEPs only. Box with po |
| touchpad | george-norton/peacock | CERN-OHL-S-2.0 | `trackpad.kicad_pcb` | STEP+STL (single case body (two tilt var) | exact | Ploopy trackpad shell (ploopyco/trackpad hardware/mechanicals/PloopyTrackpad-Rev |

Full detail (all candidates, paths, notes) in `shell-sources.json`.

Caveats: Ploopy repos ship shells but use Altium PCBs, not KiCad. No true DMG Game Boy, flip phone, power strip, TV, GameCube-style or speaker shell exists with a KiCad PCB. Several repos carry no licence.