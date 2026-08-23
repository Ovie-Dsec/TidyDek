APP_NAME = "TidyDek"
VERSION = "2.0.0"

# ============================================================
# SINGLE SOURCE OF TRUTH - identity & version for TidyDek.
#
# LAYOUT CONTRACT (enforced by tests/test_version_ssot.py):
#   Lines 1-2 MUST be exactly the two assignments above, in this
#   order, because installer/TidyDek.iss parses them with ISPP
#   FileOpen/FileRead at compile time (line-oriented reads).
#   Do NOT prepend comments, docstrings, or blank lines here.
#
# Consumers deriving from this file:
#   - pyproject.toml       [tool.setuptools.dynamic] version attr
#   - installer/TidyDek.iss ISPP extraction at compile time
#   - build.py             artifact naming and banners
#   - runtime UI           window title / tray tooltip
#
# Bump rules (Semantic Versioning):
#   MAJOR  breaking changes
#   MINOR  new features, backwards compatible
#   PATCH  fixes only
# ============================================================
