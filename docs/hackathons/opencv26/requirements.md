# OpenCV AI Competition 2026: requirements checklist

Source: https://opencv26.devpost.com/ (rules and overview, read 2026-10-26). Deadline: Oct 26, 2026, 11:45 PM PDT on the page.

| # | Requirement | Where it is met | Status |
|---|---|---|---|
| 1 | Uses OpenCV 5 for substantive image analysis | `server/src/bara/vision/measure.py` (ArUco, perspective rectification, segmentation, contours), pinned `opencv-python-headless==5.0.0.93` | done |
| 2 | A meaningful component runs on AWS | Lambda `tangible-fit-measure` (arm64 Graviton, python3.12) runs every measurement; `server/aws/` | done, live |
| 3 | Technical report: problem, users, architecture, OpenCV 5, AWS deployment, evaluation, limitations, responsible use | `docs/hackathons/opencv26/report.md` | done |
| 4 | Repo judges can access | https://github.com/PranavAchar01/bara, branch `opencv-aws` (public) | done |
| 5 | Pinned dependencies, build / deploy / test instructions | `server/pyproject.toml` + `uv.lock`, `server/aws/deploy.py` PINS, report section 10, README | done |
| 6 | Architecture diagram | `docs/hackathons/opencv26/architecture.svg` / `.png` | done |
| 7 | Working web endpoint or live screen-share demo | Lambda function URL (public); full app runs locally, screen share on request | done |
| 8 | Video, 5 minutes or less, public or unlisted, showing team, app working, architecture, results | YouTube (unlisted), link in the Devpost entry | in progress |
| 9 | Evaluation evidence including failure cases | `eval/results.json`, report section 7, `e2e/` screenshots | done (synthetic photos) |
| 10 | Prior work disclosed | report header, Devpost text: Cal Hacks 13.0 line | done |
| 11 | Eligibility: entrant 13 or older | profile | done |

Judging weights: technical execution 30%, innovation 20%, impact 20%, UX 10%, documentation and presentation 10%, cloud delivery / reproducibility / responsible operations 10%.

Special prizes:
- Agentic Vision: visual evidence must change the agent's next action. The fit check's action (build, shrink, height edit, report, retake) is chosen from the measurement. Entered.
- COOL on Graviton: needs COOL from AWS Marketplace. Not used, not entered.
