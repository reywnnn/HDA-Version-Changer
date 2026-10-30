"""Dialog that switches one chosen asset node of the open scene to another HDA version.

The dialog lists the nodes of the asset family, offers every version the chosen node does not
use yet, and shows the target file, the target operator and the node's new name. Update and
Transfer calls upgrade.run() for that node. The full report goes to the Script Editor and the
status field shows the result of the last run until it is cleared. show() replaces an open
dialog instead of opening a second one.
"""



import traceback
from PySide6 import QtCore, QtGui, QtWidgets
import maya.cmds as cmds
from ..core import planning, report
from ..core.config import SILO_GEN, UpgradeConfig
from ..scene import upgrade
from . import shelf_button



WINDOW_TITLE = "HDA Version Changer"

WINDOW_OBJECT_NAME = "hdaVersionChangerDialog"

_MAYA_WINDOW_OBJECT_NAME = "MayaWindow"

_ABOUT_ICON_SIZE = 25

_dialog_instance = None


def _maya_main_window():
    """Return Maya's main window, used as the dialog's parent.
    Returns None if the tool does not run in Maya."""
    for widget in QtWidgets.QApplication.topLevelWidgets():
        if widget.objectName() == _MAYA_WINDOW_OBJECT_NAME:
            return widget
    return None


def _window_icon():
    """Return the window icon.
    Returns None if the icon file is missing or cannot be loaded."""
    path, exists = shelf_button.get_icon_path()
    if not exists:
        return None
    icon = QtGui.QIcon(path)
    return None if icon.isNull() else icon


def _highlighted_icon(path, size):
    """Return an icon that lights up while the mouse is over its button."""
    pixmap = QtGui.QIcon(path).pixmap(size, size)
    lit = QtGui.QPixmap(pixmap)
    painter = QtGui.QPainter(lit)
    painter.setCompositionMode(QtGui.QPainter.CompositionMode_SourceAtop)
    painter.fillRect(lit.rect(), QtGui.QColor(255, 255, 255, 150))
    painter.end()
    icon = QtGui.QIcon(pixmap)
    icon.addPixmap(lit, QtGui.QIcon.Active)
    return icon


def _separator():
    line = QtWidgets.QFrame()
    line.setFrameShape(QtWidgets.QFrame.HLine)
    line.setFrameShadow(QtWidgets.QFrame.Sunken)
    return line


def _read_only_field():
    field = QtWidgets.QLineEdit()
    field.setReadOnly(True)
    return field


class AboutDialog(QtWidgets.QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About %s" % WINDOW_TITLE)
        self.setWindowFlags(QtCore.Qt.Dialog | QtCore.Qt.WindowTitleHint | QtCore.Qt.WindowCloseButtonHint)
        icon = _window_icon()
        if icon is not None:
            self.setWindowIcon(icon)

        version = shelf_button.get_installed_version() or "not an installed build"
        contact = QtWidgets.QLabel(
            "HDA Version Changer: <b>%s</b><br><br>"
            "E-Mail: <b>pavel.cirus@scssoft.com</b><br>"
            "Mattermost: <b>paul</b> <i>(Technical Art Development)</i><br><br>"
            "Feel free to contact me with any bugs, comments, or questions." % version)
        contact.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)

        credits = QtWidgets.QLabel(
            "<b>Credits:</b> "
            "Legacy library 'hda_parms' and the approach of reading values from the saved .ma file "
            "are inspired by the work of Arthur Novotný.")
        credits.setWordWrap(True)
        credits.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)
        layout.setSizeConstraint(QtWidgets.QLayout.SetFixedSize)
        layout.addWidget(contact)
        layout.addWidget(_separator())
        layout.addWidget(credits)
        credits.setFixedWidth(max(contact.sizeHint().width(), 360))


class VersionDialog(QtWidgets.QDialog):

    def __init__(self, config: UpgradeConfig = SILO_GEN, parent=None):
        super().__init__(parent)
        self._config = config
        self._busy = False
        self._last_selected = None

        self.setObjectName(WINDOW_OBJECT_NAME)
        self.setWindowTitle(WINDOW_TITLE)
        self.setWindowFlags(QtCore.Qt.Window)
        icon = _window_icon()
        if icon is not None:
            self.setWindowIcon(icon)
        self.setMinimumWidth(620)

        self._build_ui()
        self._refresh_nodes()
        self.setFixedHeight(self.sizeHint().height())


    # === construction ==================================================================


    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)

        self._node_menu = QtWidgets.QComboBox()
        self._node_menu.setPlaceholderText("No %s node in the scene" % self._config.asset_family.rsplit("/", 1)[-1])
        self._node_menu.currentIndexChanged.connect(self._on_node_changed)
        form.addRow("Selected Node", self._node_menu)
        form.addRow(_separator())

        self._version_menu = QtWidgets.QComboBox()
        self._version_menu.currentIndexChanged.connect(self._on_version_changed)
        form.addRow("Available Versions", self._version_menu)

        self._path_field = _read_only_field()
        open_folder = self._path_field.addAction(QtGui.QIcon(":/SP_DirClosedIcon.png"),
                                                 QtWidgets.QLineEdit.TrailingPosition)
        open_folder.setToolTip("Open the folder with the HDA files")
        open_folder.triggered.connect(self._on_open_folder)
        form.addRow("File Path", self._path_field)

        self._asset_field = _read_only_field()
        form.addRow("Asset Type", self._asset_field)

        self._name_field = _read_only_field()
        form.addRow("New Asset Name", self._name_field)
        form.addRow(_separator())
        layout.addLayout(form)

        bottom = QtWidgets.QHBoxLayout()
        bottom.setSpacing(8)
        self._update_button = QtWidgets.QPushButton("Update and Transfer")
        self._update_button.setToolTip("Switch the selected node to the chosen version and transfer its "
                                       "parameter values. Changes this scene. Not saving is the undo.")
        self._update_button.clicked.connect(self._on_update)
        bottom.addWidget(self._update_button)
        bottom.addWidget(self._build_status_field(), 1)
        bottom.addWidget(self._build_about_button())
        layout.addLayout(bottom)

    def _build_status_field(self):
        """Return the field that shows the result of the last run.
        The clear icon at its end empties it."""
        self._status_field = _read_only_field()
        self._status_field.setObjectName("statusField")
        font = QtGui.QFont("Consolas")
        font.setStyleHint(QtGui.QFont.Monospace)
        font.setPointSize(8)
        self._status_field.setFont(font)

        clear = self._status_field.addAction(self.style().standardIcon(QtWidgets.QStyle.SP_LineEditClearButton),
                                             QtWidgets.QLineEdit.TrailingPosition)
        clear.setToolTip("Clear the status")
        clear.triggered.connect(lambda: self._set_status(""))
        return self._status_field

    def _build_about_button(self):
        button = QtWidgets.QToolButton()
        button.setIcon(_highlighted_icon(":/pickOtherComp.png", _ABOUT_ICON_SIZE))
        button.setIconSize(QtCore.QSize(_ABOUT_ICON_SIZE, _ABOUT_ICON_SIZE))
        button.setAutoRaise(True)
        button.setStyleSheet("QToolButton { border: none; background: transparent; }")
        button.setFocusPolicy(QtCore.Qt.NoFocus)
        button.setToolTip("About %s" % WINDOW_TITLE)
        button.clicked.connect(lambda: AboutDialog(self).exec())
        return button


    # === state =========================================================================


    def changeEvent(self, event):
        """Read the scene again each time the dialog becomes active, because the scene can change meanwhile."""
        super().changeEvent(event)
        if event.type() == QtCore.QEvent.ActivationChange and self.isActiveWindow() and not self._busy:
            self._refresh_nodes()

    def _refresh_nodes(self, keep_uuid=None):
        """Fill the node menu again and keep the chosen node, or the node with keep_uuid.
        A family node that was selected in Maya since the last refresh is chosen instead."""
        try:
            nodes = upgrade.find_nodes(self._config)
        except Exception as error:
            nodes = []
            self._set_status("The scene could not be read: %s" % error)

        current = self._current_node()
        selected = _selected_node(nodes)
        if keep_uuid is not None:
            current = next((node for node in nodes if _uuid(node) == keep_uuid), current)
        elif selected is not None and selected != self._last_selected:
            current = selected
        self._last_selected = selected

        self._node_menu.blockSignals(True)
        self._node_menu.clear()
        for node in nodes:
            self._node_menu.addItem(node.split("|")[-1], node)
        self._node_menu.setCurrentIndex(nodes.index(current) if current in nodes else (0 if nodes else -1))
        self._node_menu.blockSignals(False)
        self._on_node_changed()

    def _on_node_changed(self, *_):
        """Offer the versions the chosen node does not use yet, keeping the chosen version if it is still offered."""
        node = self._current_node()
        current = self._version_menu.currentText()
        versions = []
        placeholder = ""
        if node is not None:
            try:
                versions = upgrade.other_versions(node, self._config)
            except Exception as error:
                self._set_status("The versions could not be listed: %s" % error)
            placeholder = "No other version is available"

        self._version_menu.blockSignals(True)
        self._version_menu.clear()
        self._version_menu.addItems(versions)
        self._version_menu.setPlaceholderText(placeholder)
        self._version_menu.setCurrentIndex(versions.index(current) if current in versions else (0 if versions else -1))
        self._version_menu.blockSignals(False)
        self._on_version_changed()

    def _on_version_changed(self, *_):
        """Show the target file, operator and new name of the chosen node and version.
        Update and Transfer stays disabled if run() would not upgrade the node."""
        node = self._current_node()
        version = self._version_menu.currentText()
        target, names = None, []
        if node is not None and version:
            try:
                target, names = upgrade.preview(version, self._config, node)
            except Exception as error:
                self._set_status("The version could not be previewed: %s" % error)

        if target is None:
            path, absolute, asset = "", "", ""
        else:
            path = planning.display_path(target.otl_path, self._config.display_root)
            absolute, asset = target.otl_path_abs, target.asset
        self._path_field.setText(path)
        self._path_field.setToolTip(absolute)
        self._asset_field.setText(asset)
        self._name_field.setText(names[0][1] if names else "")
        self._update_button.setEnabled(bool(names) and not self._busy)

    def _current_node(self):
        return self._node_menu.currentData()

    def _set_status(self, text):
        self._status_field.setText(text)
        self._status_field.setCursorPosition(0)
        self._status_field.setToolTip(text)

    def _set_busy(self, busy):
        """Set or clear the running state and disable the button during a run."""
        self._busy = busy
        self._update_button.setEnabled(not busy)
        if busy:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            QtWidgets.QApplication.processEvents()
        else:
            QtWidgets.QApplication.restoreOverrideCursor()


    # === actions =======================================================================


    def _on_update(self):
        """Upgrade the chosen node and show the result in the status field.
        The node is found again by its UUID afterwards, because the upgrade renames it."""
        node = self._current_node()
        version = self._version_menu.currentText()
        if node is None or not version:
            return
        uuid = _uuid(node)

        self._set_status("Updating %s to %s ..." % (node.split("|")[-1], version))
        self._set_busy(True)
        try:
            result = upgrade.run(version, config=self._config, node=node)
        except (RuntimeError, OSError) as error:
            print("Result: failed, the scene was not changed.")
            cmds.warning("The upgrade failed, the scene was not changed: %s" % error)
            status = "Failed, the scene was not changed: %s" % error
        except Exception as error:
            traceback.print_exc()
            status = "The upgrade stopped with an error, see the Script Editor: %s" % error
        else:
            status = report.format_status(result)
        finally:
            self._set_busy(False)

        self._set_status(status)
        self._refresh_nodes(keep_uuid=uuid)

    def _on_open_folder(self):
        try:
            folder = upgrade.hda_folder(self._config)
        except RuntimeError as error:
            QtWidgets.QMessageBox.warning(self, "HDA folder", str(error))
            return
        if not QtCore.QDir(folder).exists():
            QtWidgets.QMessageBox.warning(self, "HDA folder", "The folder does not exist:\n\n%s" % folder)
            return
        if not QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(folder)):
            self._set_status("Could not open %s." % folder)


def _uuid(node):
    """Return the UUID of the node, or None if the node does not exist."""
    return (cmds.ls(node, uuid=True) or [None])[0]


def _selected_node(nodes):
    """Return the node of nodes that is selected in Maya or holds a selected object.
    Returns None if no such node is selected."""
    for selected in cmds.ls(selection=True, long=True) or []:
        for node in nodes:
            if selected == node or selected.startswith(node + "|"):
                return node
    return None


def find_open_dialogs():
    """Find open dialogs by object name among QApplication's widgets.
    This is needed because Qt objects can outlive the module that created them."""
    found = []
    for widget in QtWidgets.QApplication.allWidgets():
        try:
            if widget.objectName() == WINDOW_OBJECT_NAME:
                found.append(widget)
        except RuntimeError:
            continue
    return found


def _close_open_dialogs():
    """Close every open dialog and return the geometry and the status text of the last one.
    Returns None and an empty text if no dialog was open."""
    geometry, status = None, ""
    for widget in find_open_dialogs():
        try:
            geometry = widget.saveGeometry()
            field = widget.findChild(QtWidgets.QLineEdit, "statusField")
            if field is not None:
                status = field.text()
            widget.close()
            widget.setParent(None)
            widget.deleteLater()
        except RuntimeError:
            continue
    return geometry, status


def show(config: UpgradeConfig = SILO_GEN):
    """Open the dialog, replacing an open one and keeping its position and status.
    Returns None and prints a warning if no HDA version can be found."""
    global _dialog_instance

    try:
        versions = upgrade.find_versions(config)
    except RuntimeError as error:
        cmds.warning(str(error))
        return None
    if not versions:
        cmds.warning("No HDA file named %s<version>.hda was found in %s." % (config.file_prefix, config.hda_folder))
        return None

    geometry, status = _close_open_dialogs()
    _dialog_instance = VersionDialog(config, parent=_maya_main_window())
    if geometry is not None:
        _dialog_instance.restoreGeometry(geometry)
    if status:
        _dialog_instance._set_status(status)

    _dialog_instance.show()
    _dialog_instance.raise_()
    _dialog_instance.activateWindow()
    return _dialog_instance
