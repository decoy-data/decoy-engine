### Changed (PyNaCl is a base dependency, F09 E-DEP, 2026-11-19)

The engine now requires `pynacl>=1.6.2,<2`. It was already in the lock through `paramiko` (the `sftp` extra). Nothing imports it yet; the vault v3 format uses it in a later change. The dev/CI lock profile has a new certified DP row, and `NOTICE` lists PyNaCl as a runtime package.
