from __future__ import annotations

from backend.features.verification.verification_identity import (
    extract_unmute_name_token,
    extract_unmute_target_user_id,
    resolve_name_from_db,
    resolve_state_chat_id,
    resolve_username_to_user_id,
    user_mention_html,
)
from backend.features.verification.verification_join_guards import (
    apply_join_guard_action,
    cache_invite_join_hint,
    collect_join_spam_signals,
    count_recent_joiners,
    handle_join_burst_guard,
    handle_join_spam_guard,
    pop_invite_join_hint,
    send_temporary_notice,
    upsert_chat_member_join,
)
from backend.features.verification.verification_state import (
    mark_challenge_released,
    resolve_verification_config_state,
    start_self_review_if_needed,
)
