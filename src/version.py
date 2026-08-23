"""Single Source of Truth for TidyDek's identity and version.

Every consumer derives from this file:
- pyproject.toml      -> [tool.setuptools.dynamic] version attr (pip builds)
- installer/TidyDek.iss -> ISPP FileOpen/Pos extraction at compile time
- build.py            -> direct import for artifact naming and banners
- runtime UI          -> window title and tray tooltip

Bump rules (semantic versioning):
    MAJOR  breaking changes
    MINOR  new features, backwards compatible
    PATCH  fixes only

Keep the two assignment lines exactly in this canonical shape; the ISPP
parser locates them by literal markers 'APP_NAME = "' / 'VERSION = "'.
"""

APP_NAME = "TidyDek"
VERSION = "2.0.0"
