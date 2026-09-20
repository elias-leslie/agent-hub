"""Agent Hub-owned ST commands and supported HTTP helper APIs.

``PUBLIC_HELPER_API_VERSION`` versions the helper-module contract documented in
the package README.  The command modules remain importable for trusted ST
registration, while integrations should depend only on the documented helpers.
"""

__version__ = "0.1.0"
PUBLIC_HELPER_API_VERSION = 1

__all__ = ["PUBLIC_HELPER_API_VERSION", "__version__"]
