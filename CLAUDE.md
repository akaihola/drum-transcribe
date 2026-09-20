# Project rules

- The user is a musician, not a software developer. Keep all documentation
  (especially README.md) up to date and understandable without programming
  knowledge — explain what each output (e.g. the sonification) *is*.
- Follow the Honey skill: minimum code that needs to exist, clean and minimal
  architecture, easy to maintain. No speculative features.
- Any step where the user listens, looks, or corrects results must be a web
  server bound to 0.0.0.0, reachable from other machines.
- Commit frequently, in small logical parts.
- Results from different pipeline variants and different songs stay in
  separate directories: `output/<song>/<variant>/`.
- Missing tools on this NixOS laptop: run via comma, e.g. `, mscore`.
