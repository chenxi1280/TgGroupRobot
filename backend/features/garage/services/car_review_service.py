from __future__ import annotations

from backend.features.garage.services.car_review_reports import CarReviewReportMixin
from backend.features.garage.services.car_review_settings import CarReviewSettingsMixin


class CarReviewService(CarReviewSettingsMixin, CarReviewReportMixin):
    pass
