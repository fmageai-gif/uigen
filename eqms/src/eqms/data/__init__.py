"""Data layer: one repository per workbook, speaking in domain models.

Repositories translate between :mod:`eqms.core.models` dataclasses and the rows
of their backing workbook, delegating all transport to the active
:class:`~eqms.sharepoint.base.ExcelStore`. They contain *no* business rules —
those live in the service layer and in editable ``Settings.xlsx`` configuration.
"""
