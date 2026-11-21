### Fixed (importing the ML stack helper no longer loads lightgbm, MLSTACK-LAZY, 2026-11-20)

`model_pack/_mlstack.py` bound `LGBMClassifier` at import time. A test that stubbed `lightgbm` without that class made the import fail, so four model-status tests passed or failed by worker order. The class now comes from `lgbm_classifier()`, which imports the stack on first call. The sklearn-before-lightgbm order for Windows is unchanged.
