"""HP Mainstream Enterprise Quality Management System (EQMS).

A production-grade Windows desktop application for the HP Mainstream Quality
Assurance team to perform and manage Short Call Audits.

The system of record is a set of Excel workbooks hosted on SharePoint; this
package provides authentication, data access, business logic, reporting and a
CustomTkinter-based desktop user interface on top of that store.
"""

__all__ = ["__version__", "APP_NAME", "APP_SHORT_NAME"]

#: Semantic version of the application. Surfaced in the UI, logs and the update
#: checker. Bump this on every release.
__version__ = "1.1.3"

#: Human-readable application name used in window titles, emails and reports.
APP_NAME = "HP Mainstream Enterprise Quality Management System"

#: Short name used in compact UI contexts and file names.
APP_SHORT_NAME = "HP Mainstream EQMS"
