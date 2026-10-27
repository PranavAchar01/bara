"""Hardware CI for Tangible boards: KiCad checks, provenance, fab outputs and GitLab reports.

Standard library only, so it runs in the plain KiCad container in CI and inside a GitLab Duo
flow without installing the rest of the engine. Everything goes through `kicad-cli`."""
