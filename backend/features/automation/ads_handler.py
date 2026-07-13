"""广告功能兼容入口；实现按命令、规则、消息项与输入职责拆分。"""
from backend.features.automation.ads_parsing import _parse_ads_config as _parse_ads_config
from backend.features.automation.ads_command import ad_command as ad_command
from backend.features.automation.ads_context import (
    AdsHandler as AdsHandler,
    _ads_handler as _ads_handler,
    _format_ad_detail_text as _format_ad_detail_text,
    _parse_ad_id_from_callback as _parse_ad_id_from_callback,
    _render_ads_home_text as _render_ads_home_text,
    _resolve_ads_target_chat_id as _resolve_ads_target_chat_id,
)
from backend.features.automation.ads_input_callbacks import (
    ads_cancel_callback as ads_cancel_callback,
    ads_create_config_message as ads_create_config_message,
)
from backend.features.automation.ads_item_callbacks import (
    ads_cleanup_callback as ads_cleanup_callback,
    ads_create_start_callback as ads_create_start_callback,
    ads_delete_callback as ads_delete_callback,
    ads_detail_callback as ads_detail_callback,
    ads_item_input_callback as ads_item_input_callback,
    ads_item_preview_callback as ads_item_preview_callback,
    ads_item_set_callback as ads_item_set_callback,
    ads_item_time_callback as ads_item_time_callback,
    ads_list_callback as ads_list_callback,
    ads_send_callback as ads_send_callback,
    ads_stats_callback as ads_stats_callback,
    ads_toggle_callback as ads_toggle_callback,
)
from backend.features.automation.ads_rule_callbacks import (
    ads_menu_callback as ads_menu_callback,
    ads_rules_callback as ads_rules_callback,
    ads_rules_input_callback as ads_rules_input_callback,
    ads_rules_set_callback as ads_rules_set_callback,
)

__all__ = [name for name in globals() if name.startswith("ads_") or name.startswith("_ads")]
