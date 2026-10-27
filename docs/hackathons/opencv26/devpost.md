# Devpost entry: OpenCV AI Competition 2026

## Project name
Tangible Fit Check

## Elevator pitch
Snap one photo of the space your gadget has to fit. OpenCV 5 on AWS Lambda measures it, and an agent resizes the device to match.

## About the project

Tangible was first shown at Cal Hacks 13.0 (Oct 24-25, 2026); the OpenCV/AWS vision feature was built for this competition.

### Inspiration
Tangible turns a sentence like "a 2x2 macropad with a volume knob" into a device built from real parts: a 3D layout, a case, a KiCad board and firmware. The case size always came from the parts, though, and real devices go somewhere specific: a gap on a shelf, a corner of a desk, the spot where an old remote used to sit. If the case is 6 mm too wide it doesn't fit, and most people don't own calipers.

### What it does
You print a 40 mm ArUco marker, lay it next to the space, and take one photo from above. OpenCV 5 finds the marker, warps the photo to a top-down view at 4 px per mm, finds the space and measures it in millimetres.

Then an agent decides what to do with that measurement:
- No device yet: it offers to build one sized to the space.
- The current case is too big: it offers a shrink-to-fit rebuild with the target size.
- It fits but is too tall: it offers a height edit.
- It fits: it tells you how much room is left.
- The photo is bad (no marker, the space is cut off, two things in frame): it retries once with CLAHE contrast boost, then asks for a retake and says why.

You see the top-down view with the outline it measured, the size, and every step it took. Nothing changes until you press approve. After the rebuild, "Check again" runs the same photo against the new case. The build engine can't enforce a size limit yet, so a shrink rebuild isn't always smaller. In the end-to-end run a 66 x 78 mm case came back at 67 x 92 mm, and "Check again" caught it.

### How we built it
- OpenCV 5.0.0: ArucoDetector with subpixel corners, getPerspectiveTransform and warpPerspective, a floodFill mask so the marker sheet isn't counted, then three segmentation strategies in order (Lab colour distance with Otsu, adaptive threshold, Canny edges), minAreaRect and approxPolyDP for size and shape, and checks for cut-off, ragged or duplicate outlines.
- AWS: the measurement runs on Lambda (arm64 Graviton, Python 3.12) behind a function URL, with one JSON log line per call in CloudWatch. A small deploy script builds pinned arm64 wheels and ships the 52 MB package through S3. If Lambda can't be reached, the engine runs the same code locally and the step trace says so.
- The agent and API live in Tangible's FastAPI engine. The panel is a React component in the existing workspace, and approvals go through the same prompt and edit paths as the rest of the app.
- The browser shrinks the photo to a 1600 px JPEG before upload, which also strips EXIF and GPS.

### Results
All numbers are on synthetic photos with known sizes (random tilt, lighting falloff, blur, noise and JPEG compression). We didn't have a labelled set of real photos in time.
- 56 scenes: 53 measured, mean error 0.42 mm, p95 1.4 mm, max 2.6 mm. Shape class right on 53 of 53. The other 3 asked for a retake or said unsure; none gave a wrong size.
- Bad photos that should get a retake: no marker 10/10, cut off 10/10, two objects 9/10.
- With a case open a few mm bigger or smaller than the space, the agent picked the right action on 53 of 56 scenes, asked for a retake on 3, and never picked a wrong one.
- Lambda vs local on the same 20 photos: 0.0 mm difference. Median 635 ms inside Lambda, about 1 s round trip, 3.4 s on a cold start.
- 9 unit tests and a Playwright run through the real app: build, fit check, approve, rebuild, check again.

### Challenges we ran into
- OpenCV 5 returns marker ids as a flat array, which broke code written for 4.x.
- Sizes came out about 9% too large until we turned on subpixel corner refinement.
- The white marker sheet kept winning the segmentation. A floodFill mask of the sheet and an Otsu threshold over the table only fixed it.
- The Lambda package is over the 50 MB direct upload limit, so it goes through S3.

### What we learned
Most of the work went into deciding when a photo can't be trusted: the marker, cut-off and two-object checks and the CLAHE retry took longer than the measuring itself.

### What's next
- A labelled set of real photos, and numbers on it.
- Two photos for height.
- Matching the curved outline of the thing being replaced, so the case follows its shape instead of a bounding box.

## Built with
opencv, python, aws-lambda, aws-graviton, amazon-s3, amazon-cloudwatch, fastapi, react, typescript, numpy, playwright, anthropic-claude

## Links
- Repo: https://github.com/PranavAchar01/bara/tree/opencv-aws
- Technical report: https://github.com/PranavAchar01/bara/blob/opencv-aws/docs/hackathons/opencv26/report.md
- Live endpoint: https://utmqhifgnhqgep65hqqhuh56aa0rukxb.lambda-url.us-west-2.on.aws/
- Video: (YouTube, unlisted)
