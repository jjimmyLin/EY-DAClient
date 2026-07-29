from __future__ import annotations

from PySide6.QtWidgets import QDialogButtonBox, QScrollArea

from ui.api_settings_dialog import ApiSettingsDialog


def test_api_settings_content_scrolls_and_save_stays_visible(qapp):
    dialog = ApiSettingsDialog()
    dialog.resize(540, 480)
    dialog.show()
    qapp.processEvents()

    scroll = dialog.findChild(QScrollArea, "apiSettingsScroll")
    buttons = dialog.findChild(QDialogButtonBox)

    assert scroll is not None
    assert scroll.verticalScrollBar().maximum() > 0
    assert buttons is not None
    assert buttons.isVisible()
    assert buttons.button(QDialogButtonBox.Save).isVisible()
    dialog.close()
