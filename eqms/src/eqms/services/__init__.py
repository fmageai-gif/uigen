"""Service layer: business logic orchestrating the data repositories.

Services own validation, KPI computation, email, reporting, backups and update
checking. They are the only layer the UI calls for actions, and they read all
configurable rules from :class:`~eqms.data.settings_store.SettingsStore` rather
than hardcoding them.
"""
