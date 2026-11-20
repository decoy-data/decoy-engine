### Changed (the multi-table split is decided with the route, NONFK-OOM S4a, 2026-11-19)

`run_pipeline` now decides which mask tables of an independent multi-table job dispatch alone while it decides the route, and stores the result on `RouteDecision.split`. The executor reads it instead of deciding after the route is published. Output is unchanged.
