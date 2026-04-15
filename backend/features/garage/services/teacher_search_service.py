from __future__ import annotations

from backend.features.garage.services.teacher_search_queries import TeacherSearchQueryMixin
from backend.features.garage.services.teacher_search_settings import TeacherSearchFooterButtonConfig, TeacherSearchSettingsMixin


class TeacherSearchService(TeacherSearchSettingsMixin, TeacherSearchQueryMixin):
    pass
