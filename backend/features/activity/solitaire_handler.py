from __future__ import annotations

from backend.features.activity.services.solitaire_service import parse_config_value as _parse_config_value
from backend.features.activity.solitaire_creation_cancel import solitaire_cancel_callback
from backend.features.activity.solitaire_creation_config import solitaire_create_config_message
from backend.features.activity.solitaire_creation_start import solitaire_create_start_callback
from backend.features.activity.solitaire_creation_wizard import (
    solitaire_create_deadline_message,
    solitaire_create_description_message,
    solitaire_create_max_message,
    solitaire_create_points_message,
    solitaire_create_title_message,
)
from backend.features.activity.solitaire_management_callbacks import (
    solitaire_close_callback,
    solitaire_delete_callback,
    solitaire_refresh_callback,
)
from backend.features.activity.solitaire_menu_callbacks import (
    solitaire_detail_callback,
    solitaire_list_callback,
    solitaire_menu_callback,
    solitaire_stats_callback,
)
from backend.features.activity.solitaire_participation_callbacks import (
    edit_solitaire_callback,
    join_solitaire_callback,
    solitaire_join_message_handler,
)
from backend.features.activity.solitaire_shared import (
    WAIT_CONFIG,
    WAIT_DEADLINE,
    WAIT_DESCRIPTION,
    WAIT_MAX_PARTICIPANTS,
    WAIT_POINTS_REQUIRED,
    SolitaireHandler,
    _solitaire_handler,
)
