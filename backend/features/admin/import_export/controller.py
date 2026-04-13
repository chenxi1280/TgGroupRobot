from __future__ import annotations

from backend.features.admin.import_export.inherit import AccountInheritAdminMixin
from backend.features.admin.import_export.quick_publish import QuickPublishAdminMixin
from backend.features.admin.import_export.settings_transfer import SettingsTransferAdminMixin


class ImportExportAdminControllerMixin(
    SettingsTransferAdminMixin,
    QuickPublishAdminMixin,
    AccountInheritAdminMixin,
):
    """Composed import/export, quick publish, and account inherit admin controller."""
