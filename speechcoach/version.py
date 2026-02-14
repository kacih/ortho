"""Single source of truth for the application version.

Keep this file minimal. Other modules (config, __init__, manifest check) should
import __version__ from here to avoid mismatch regressions.
"""

__version__ = "7.22.0"
