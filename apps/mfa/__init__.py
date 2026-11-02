# Two-factor sign-in for Civil — a self-contained app.
#
# Nothing in here imports from `apps.identity` or any other Civil app:
# Mercantil and Jackil copy this directory whole, and everything app-specific
# arrives through settings (see `conf.py`).
#
# Callers reach the staff reset as `from apps.mfa.service import reset`. It is
# not re-exported here: Django imports this module to discover the app, and an
# import of models.py from here would touch the ORM before the registry is
# ready.
