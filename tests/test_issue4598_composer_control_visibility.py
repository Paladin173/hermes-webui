"""Static-contract regression tests for the composer footer-control visibility
toggles (#4598).

Mirrors the sibling pattern in test_sidebar_tab_visibility.py: pins that each
toggle is wired end-to-end (config boolean key -> boot.js definition + read-back
-> index.html control -> panels.js chip render -> apply) and that every new i18n
key exists across all locale blocks, so a future refactor can't silently orphan
a control or break locale parity.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PY = (ROOT / "api" / "config.py").read_text(encoding="utf-8")
PANELS_JS = (ROOT / "static" / "panels.js").read_text(encoding="utf-8")
BOOT_JS = (ROOT / "static" / "boot.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
I18N_JS = (ROOT / "static" / "i18n.js").read_text(encoding="utf-8")
STYLE_CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")

# The 15 composer-control visibility flags this feature ships.
HIDE_KEYS = [
    "hide_composer_attach",
    "hide_composer_saved_prompts",
    "hide_composer_mic",
    "hide_composer_voice_mode",
    "hide_composer_yolo",
    "hide_composer_profile",
    "hide_composer_workspace",
    "hide_composer_mobile_config",
    "hide_composer_model",
    "hide_composer_quota_chip",
    "hide_composer_reasoning",
    "hide_composer_toolsets",
    "hide_composer_status",
    "hide_composer_context",
    "hide_composer_bg_badge",
]

# The new i18n keys the feature adds (section labels/descriptions + per-chip labels).
I18N_KEYS = [
    "settings_label_composer_controls",
    "settings_desc_composer_controls",
    "settings_label_composer_situational_controls",
    "settings_desc_composer_situational_controls",
    "composer_control_attach",
    "composer_control_saved_prompts",
    "composer_control_mic",
    "composer_control_profile",
    "composer_control_workspace",
    "composer_control_model",
    "composer_control_reasoning",
    "composer_control_context",
    "composer_control_voice_mode",
    "composer_control_yolo",
    "composer_control_bg_badge",
    "composer_control_mobile_config",
    "composer_control_quota_chip",
    "composer_control_toolsets",
    "composer_control_status",
]


def test_all_hide_flags_registered_as_boolean_settings_keys():
    """Every toggle must be in config.py's boolean-keys set so it persists and
    round-trips through save/load."""
    for key in HIDE_KEYS:
        assert f'"{key}"' in CONFIG_PY, f"{key} missing from config.py boolean settings keys"


def test_hide_composer_send_orphan_key_fully_removed():
    """The re-push removed the orphaned hide_composer_send key (Send is always
    visible) — it must not linger anywhere."""
    assert "hide_composer_send" not in CONFIG_PY
    assert "hide_composer_send" not in BOOT_JS
    assert "hide_composer_send" not in PANELS_JS


def test_footer_control_chips_rendered_in_panels():
    """panels.js must render the primary + situational control chips and apply
    the visibility settings live."""
    assert "_renderComposerControlChips" in PANELS_JS
    assert "_ensureComposerControlVisibilityState" in PANELS_JS
    assert "_applyComposerFooterVisibilitySettings" in PANELS_JS


def test_composer_control_order_is_persisted_and_draggable(monkeypatch, tmp_path):
    """Composer footer controls can be drag-sorted from Settings and the order
    round-trips through settings.json."""
    import api.config as config

    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(config, "SETTINGS_FILE", settings_path)

    loaded = config.load_settings()
    assert loaded["composer_control_order"] == []

    saved = config.save_settings({
        "composer_control_order": [
            "hide_composer_model",
            "hide_composer_quota_chip",
            "hide_composer_model",
            "",
            42,
            "hide_composer_fake",
            "hide_composer_workspace",
        ]
    })
    assert saved["composer_control_order"] == [
        "hide_composer_model",
        "hide_composer_quota_chip",
        "hide_composer_workspace",
    ]
    assert config.load_settings()["composer_control_order"] == saved["composer_control_order"]

    assert "composer_control_order" in config._SETTINGS_ALLOWED_KEYS
    assert "composer_control_order" not in config._SETTINGS_BOOL_KEYS


def test_composer_control_order_frontend_contracts():
    """Frontend must expose composer order helpers, drag chips, and include the
    order in Appearance autosave."""
    for fn in (
        "_sanitizeComposerControlOrder",
        "_orderedComposerControlDefs",
        "_applyComposerControlOrder",
    ):
        assert f"function {fn}(" in BOOT_JS, f"boot.js must define {fn}()"
    for fn in (
        "_getComposerControlOrder",
        "_setComposerControlOrder",
        "_wireComposerControlChipDrag",
        "_moveComposerControlOrderKey",
        "_handleComposerControlChipDrop",
    ):
        assert f"function {fn}(" in PANELS_JS, f"panels.js must define {fn}()"

    assert "orderSelector" in BOOT_JS
    assert "insertBefore" in BOOT_JS
    assert "selectors:['#providerQuotaChip','#composerMobileQuotaAction']" in BOOT_JS
    assert "window._composerControlOrder=_sanitizeComposerControlOrder(s.composer_control_order)" in BOOT_JS
    assert "composer_control_order: _getComposerControlOrder()" in PANELS_JS
    assert "composer_control_order" in CONFIG_PY

    render_body = PANELS_JS[PANELS_JS.index("function _renderComposerControlChips("):PANELS_JS.index("function switchSettingsSection(")]
    assert "_COMPOSER_CONTROL_FALLBACK_DEFS" not in PANELS_JS
    assert "_composerControlDefsForSettings" in PANELS_JS
    assert "_orderedComposerControlDefsForSettings" in render_body
    assert "_composerControlDefsForSettings()" in render_body
    assert "_wireComposerControlChipDrag" in render_body
    assert "data-composer-control-key" in PANELS_JS
    assert "application/x-hermes-composer-control" in PANELS_JS
    assert "pointerdown" in PANELS_JS and "pointermove" in PANELS_JS and "pointerup" in PANELS_JS
    assert "document.elementFromPoint" in PANELS_JS
    assert "_composerControlPointerDrag" in PANELS_JS
    assert "_COMPOSER_CONTROL_LONG_PRESS_MS" in PANELS_JS
    assert "_COMPOSER_CONTROL_TOUCH_CANCEL_PX" in PANELS_JS
    assert "longPressTimer=setTimeout" in PANELS_JS
    assert "clearTimeout(drag.longPressTimer)" in PANELS_JS
    assert "pointerType==='touch'" in PANELS_JS
    assert "drag-armed" in PANELS_JS
    assert "contextmenu" in PANELS_JS
    assert "navigator.vibrate" in PANELS_JS
    assert "const sourceKey=e&&e.dataTransfer" in PANELS_JS
    assert "_renderComposerSituationalControlChips" not in PANELS_JS
    assert "draggable" in PANELS_JS
    assert "dragstart" in PANELS_JS and "drop" in PANELS_JS
    assert "_composerControlDragSuppressUntil" in PANELS_JS and "Date.now()+250" in PANELS_JS
    assert "#composerControlsChips .tab-visibility-chip" in STYLE_CSS
    assert "touch-action:none" in STYLE_CSS
    assert "-webkit-touch-callout:none" in STYLE_CSS
    assert ".tab-visibility-chip.drag-armed" in STYLE_CSS
    assert ".tab-visibility-chip.dragging" in STYLE_CSS
    assert ".tab-visibility-chip.drag-over" in STYLE_CSS


def test_new_i18n_keys_exist_across_all_locale_blocks():
    """Every new i18n key must appear in all 13 locale blocks (strict locale
    parity), not just `en` — otherwise the locale-coverage suite goes red."""
    # 13 locale blocks (en + 12). Each key should appear at least 13 times.
    for key in I18N_KEYS:
        count = I18N_JS.count(f"{key}:")
        assert count >= 13, (
            f"{key} appears {count}x in i18n.js — expected >=13 (one per locale "
            f"block) for strict locale parity"
        )

    assert "Drag chips to reorder the footer." in INDEX_HTML
    assert "Some controls only appear for certain viewport, mode, or runtime states." in INDEX_HTML
    assert "Reordering is not supported." not in I18N_JS
    assert "La réorganisation n\\'est pas prise en charge" not in I18N_JS
    assert "Không hỗ trợ đổi thứ tự" not in I18N_JS

    for key in (
        "hide_composer_attach",
        "hide_composer_saved_prompts",
        "hide_composer_mic",
        "hide_composer_profile",
        "hide_composer_workspace",
        "hide_composer_model",
        "hide_composer_reasoning",
        "hide_composer_context",
        "hide_composer_voice_mode",
        "hide_composer_yolo",
        "hide_composer_bg_badge",
        "hide_composer_mobile_config",
        "hide_composer_quota_chip",
        "hide_composer_toolsets",
        "hide_composer_status",
    ):
        assert key in BOOT_JS
