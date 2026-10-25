# Simulation status

Measured on a clean engine with `server/scripts/sim_sweep.py` (boot, then every input part is driven and every output part watched) and a surface check per build (every control maps to a real input, every real input has a control).

## Generic devices built live (prompts were generic)

| device | boots | inputs work | outputs work | surface shows only real inputs |
|---|---|---|---|---|
| Handheld game console | yes | 9/9 | 4/4 | yes |
| Macropad | yes | 10/10 | 1/1 | yes |
| Kitchen timer | yes | 2/2 | 3/3 | yes |
| Bike light | yes | 1/1 | 4/4 | yes |
| Plant monitor | yes | 5/5 | 3/3 | yes |

## Library (181 builds)

- Boots on emulated firmware: 135
- Cannot boot: 46, all with the same reason: the build has no controller part, so there is no firmware to run (the panel says so).
- Inputs that produced a visible or audible response: 2799 of 2799
- Outputs that showed life: 283 of 287
- Surfaces checked against the parts: 135; controls outside the real inputs: 0; real inputs without a control: 0

| device | builds | inputs work | outputs work | surface shows only real inputs |
|---|---|---|---|---|
| Key finder tag | 3 | 3/3 | 9/9 | yes |
| Dice roller | 1 | 5/5 | 3/3 | yes |
| Parking sensor | 1 | 0/0 | 2/2 | yes |
| Pocket morse trainer | 1 | 4/4 | 3/3 | yes |
| Kids night light | 1 | 0/0 | 2/2 | yes |
| Kitchen egg timer | 1 | 3/3 | 2/2 | yes |
| Arcade single-joystick box | 1 | 9/9 | 1/1 | yes |
| Handheld golf stroke counter | 1 | 2/2 | 2/2 | yes |
| Wireless split keyboard | 21 | 836/836 | 24/24 | yes |
| Pocket unit converter | 1 | 5/5 | 2/2 | yes |
| Desk volume controller | 1 | 7/7 | 2/2 | yes |
| Clip-on backpack safety blin | 1 | 1/1 | 3/3 | yes |
| Small 5x4 macropad | 16 | 336/336 | 32/32 | yes |
| Keyboard | 8 | 488/488 | 8/8 | yes |
| Replace the bottom spacbar | 1 | 1/1 | 1/1 | yes |
| Low-profile mechanical keybo | 3 | 183/183 | 4/4 | yes |
| Pocket voice recorder | 2 | 24/24 | 7/7 | yes |
| TV remote | 3 | 59/59 | 5/5 | yes |
| Cooking meat thermometer | 3 | 13/13 | 8/8 | yes |
| Pocket step counter | 1 | 3/3 | 2/2 | yes |
| Wireless doorbell button | 1 | 1/1 | 1/1 | yes |
| Pocket dice roller | 1 | 4/4 | 4/4 | yes |
| Smart pill box | 2 | 20/20 | 6/6 | yes |
| Desk fan controller | 1 | 2/2 | 1/1 | yes |
| 60% keyboard | 2 | 122/122 | 2/2 | yes |
| Pocket weather station | 1 | 8/8 | 3/3 | yes |
| People tally counter | 2 | 5/5 | 6/6 | yes |
| Plant soil moisture monitor | 1 | 5/5 | 3/3 | yes |
| Calculator | 3 | 10/10 | 5/5 | yes |
| Wireless game controller | 5 | 121/121 | 8/12 | yes |
| Handheld arcade device | 4 | 68/68 | 17/17 | yes |
| Desk calculator | 2 | 21/21 | 4/4 | yes |
| Bike tail light | 2 | 3/3 | 8/8 | yes |
| Plant moisture sensor | 1 | 5/5 | 3/3 | yes |
| Metronome | 1 | 6/6 | 6/6 | yes |
| Wireless presenter clicker | 1 | 2/2 | 3/3 | yes |
| Handheld tally counter | 1 | 4/4 | 4/4 | yes |
| Kitchen scale readout | 1 | 5/5 | 2/2 | yes |
| Bike light remote | 1 | 3/3 | 1/1 | yes |
| Doorbell | 1 | 2/2 | 4/4 | yes |
| Plant moisture monitor | 1 | 5/5 | 3/3 | yes |
| Pocket metronome | 1 | 2/2 | 2/2 | yes |
| Handheld metronome | 1 | 4/4 | 4/4 | yes |
| Desk timer cube | 1 | 4/4 | 3/3 | yes |
| Kitchen timer | 1 | 2/2 | 3/3 | yes |
| Desk clock | 2 | 7/7 | 5/5 | yes |
| Macropad | 1 | 10/10 | 1/1 | yes |
| Joystick controller | 2 | 35/35 | 2/2 | yes |
| Bike rear light | 1 | 2/2 | 3/3 | yes |
| Portable bluetooth speaker | 1 | 4/4 | 1/1 | yes |
| Stream deck | 1 | 9/9 | 1/1 | yes |
| Handheld game console | 10 | 150/150 | 31/31 | yes |
| Game controller | 3 | 72/72 | 3/3 | yes |
| 34-key split | 2 | 72/72 | 2/2 | yes |
| Gameboy | 2 | 22/22 | 6/6 | yes |

## What does not work yet

- Four wireless game controller builds have one indicator LED that the firmware does not drive (it sits on a power rail, not a pin). The panel still lists it; it never lights.
- Builds without a controller part cannot simulate (46 of the Library).
- The first open of a build compiles the firmware (about 1 to 5 s); presses before it is running are ignored.
- Surface text depends on a model call; when none answers the panel falls back to labels derived from the parts.
