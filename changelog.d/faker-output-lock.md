### Added (Faker output lock and test-only clock freeze, FAKER-MIGRATE, 2026-11-18)

`scripts/faker-determinism/output_lock.json` now records digests of what Faker returns for every locale on the two surfaces the engine uses, and a required CI job fails when a Faker release changes them. The lock is captured under Faker 40.23.0, so the later repin shows exactly which provider and locale pairs move. `time-machine` joins the `dev` extra to freeze the clock in the lock's worker processes, and `_CERTIFIED_STACKS` gains the matching dev/CI row. No runtime behavior changes.
