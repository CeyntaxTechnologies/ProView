import os
import sys
import shutil
import ctypes
import subprocess
import platform
from PySide6 import QtCore, QtGui, QtWidgets

# Import the duplicate finder module
from duplicate_finder import DuplicateFilesDialog

# ---------- Colors ----------
DARK_BLUE = QtGui.QColor(10, 60, 160)
BLACK = QtGui.QColor(0, 0, 0)
WHITE = QtGui.QColor(245, 245, 245)
PURPLE = QtGui.QColor(124, 58, 237)
GREEN = QtGui.QColor(16, 185, 129)
DARK_GREEN = QtGui.QColor(22, 101, 52)
LIGHT_GRAY = QtGui.QColor(230, 230, 230)
SOFT_GRAY = QtGui.QColor(200, 200, 200)

# ---------- Message Box Style ----------
MESSAGE_BOX_STYLE = """
    QMessageBox {
        background-color: white;
    }
    QMessageBox QLabel {
        color: black;
    }
"""


# ---------- Utilities ----------
def list_drives():
    drives = []
    if os.name == "nt":
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for i in range(26):
            if bitmask & (1 << i):
                drive = f"{chr(65 + i)}:\\"
                drive_type = ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(drive))
                if drive_type in (2, 3, 4, 5, 6):
                    # Get volume label
                    volume_name_buffer = ctypes.create_unicode_buffer(1024)
                    file_system_buffer = ctypes.create_unicode_buffer(1024)

                    result = ctypes.windll.kernel32.GetVolumeInformationW(
                        ctypes.c_wchar_p(drive),
                        volume_name_buffer,
                        ctypes.sizeof(volume_name_buffer),
                        None,
                        None,
                        None,
                        file_system_buffer,
                        ctypes.sizeof(file_system_buffer)
                    )

                    volume_name = volume_name_buffer.value if result and volume_name_buffer.value else ""

                    # Create drive label
                    if drive_type == 2:
                        if volume_name:
                            drive_label = f"{drive} - {volume_name} (Removable)"
                        else:
                            drive_label = f"{drive} - Removable Drive"
                    else:
                        if volume_name:
                            drive_label = f"{drive} - {volume_name}"
                        else:
                            drive_label = drive

                    drives.append((drive, drive_label))
    else:
        drives = [("/", "/")]
        for base in ("/Volumes", "/media", "/mnt"):
            if os.path.isdir(base):
                for name in os.listdir(base):
                    p = os.path.join(base, name)
                    if os.path.ismount(p):
                        drives.append((p, f"{p} - Removable Drive"))
    return drives


def open_file_with_default_app(file_path):
    """Open a file with the system's default application"""
    try:
        if platform.system() == 'Windows':
            os.startfile(file_path)
        elif platform.system() == 'Darwin':  # macOS
            subprocess.run(['open', file_path])
        else:  # Linux and other Unix-like systems
            subprocess.run(['xdg-open', file_path])
        print(f"Opened file: {file_path}")
        return True
    except Exception as e:
        print(f"Error opening file {file_path}: {e}")
        return False


# ---------- Delegate ----------
class FileColorDelegate(QtWidgets.QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        model = index.model()
        if isinstance(model, QtWidgets.QFileSystemModel):
            is_dir = model.isDir(index)
        else:
            is_dir = os.path.isdir(model.filePath(index)) if hasattr(model, 'filePath') else False
        option.palette.setColor(QtGui.QPalette.Text, BLACK if is_dir else DARK_BLUE)


# ---------- Custom TreeView with Drag/Drop ----------
class DragDropTreeView(QtWidgets.QTreeView):
    file_dropped = QtCore.Signal(list, str)  # source_paths, destination_dir

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDrop)

    def mouseDoubleClickEvent(self, event):
        """Handle double-click events to open files"""
        if event.button() == QtCore.Qt.LeftButton:
            index = self.indexAt(event.pos())
            if index.isValid():
                file_path = self.model().filePath(index)

                if os.path.isfile(file_path):
                    # It's a file, try to open it
                    success = open_file_with_default_app(file_path)
                    if not success:
                        # Show error message if file couldn't be opened
                        msg = QtWidgets.QMessageBox(self)
                        msg.setWindowTitle("Open File Error")
                        msg.setText(
                            f"Could not open file:\n{os.path.basename(file_path)}\n\nThe file may not have an associated application.")
                        msg.setIcon(QtWidgets.QMessageBox.Warning)
                        msg.setStyleSheet(MESSAGE_BOX_STYLE)
                        msg.exec()
                    return  # Don't call parent's double-click for files

        # For directories or if not a valid index, use default behavior (expand/collapse)
        super().mouseDoubleClickEvent(event)

    def startDrag(self, supportedActions):
        indexes = self.selectedIndexes()
        if not indexes:
            return

        # Get unique rows (since we have multiple columns per row)
        rows = list(set(idx.row() for idx in indexes if idx.column() == 0))
        if not rows:
            return

        # Create drag data
        drag = QtGui.QDrag(self)
        mimeData = QtCore.QMimeData()

        # Store file paths
        paths = []
        for row in rows:
            idx = self.model().index(row, 0, indexes[0].parent())
            if idx.isValid():
                paths.append(self.model().filePath(idx))

        mimeData.setText('\n'.join(paths))
        drag.setMimeData(mimeData)

        # Start drag operation
        dropAction = drag.exec(QtCore.Qt.CopyAction | QtCore.Qt.MoveAction)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasText():
            event.ignore()
            return

        # Get drop position
        pos = event.pos()
        idx = self.indexAt(pos)

        # Determine destination directory
        if idx.isValid():
            if self.model().isDir(idx):
                dest_dir = self.model().filePath(idx)
            else:
                # Dropped on a file, use its parent directory
                parent_idx = idx.parent()
                dest_dir = self.model().filePath(parent_idx) if parent_idx.isValid() else self.model().rootPath()
        else:
            # Dropped in empty space, use root
            dest_dir = self.model().rootPath()

        # Get source paths
        source_paths = event.mimeData().text().strip().split('\n')
        source_paths = [p for p in source_paths if p and os.path.exists(p)]

        if source_paths:
            self.file_dropped.emit(source_paths, dest_dir)

        event.acceptProposedAction()


# ---------- Drive Panel ----------
class DriveTree(QtWidgets.QWidget):
    request_paste_here = QtCore.Signal(str)
    request_copy = QtCore.Signal(list)
    request_move = QtCore.Signal(list)
    clicked = QtCore.Signal(object)
    file_dropped = QtCore.Signal(list, str)

    def __init__(self, drive_path: str, drive_label: str, parent=None):
        super().__init__(parent)
        self.drive_path = drive_path
        self.drive_label = drive_label
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        self.header = QtWidgets.QLabel(f"{drive_label}")
        self.header.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        self.header.setStyleSheet(f"font-weight: 600; font-size: 14px; color: #111;")
        layout.addWidget(self.header)

        self.model = QtWidgets.QFileSystemModel(self)
        self.model.setReadOnly(False)
        self.model.setRootPath(drive_path)

        self.tree = DragDropTreeView(self)
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(drive_path))
        self.tree.setAlternatingRowColors(True)
        self.tree.setEditTriggers(
            QtWidgets.QAbstractItemView.EditKeyPressed | QtWidgets.QAbstractItemView.SelectedClicked)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.open_context_menu)
        self.tree.setItemDelegate(FileColorDelegate(self.tree))
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, QtCore.Qt.AscendingOrder)
        self.tree.setExpandsOnDoubleClick(True)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.setHeaderHidden(False)
        self.tree.header().setStretchLastSection(True)
        self.tree.clicked.connect(self.on_tree_clicked)
        self.tree.file_dropped.connect(self.file_dropped.emit)
        self.tree.setStyleSheet(f"""
            QTreeView {{
                background: {WHITE.name()};
                border: 1px solid #DDD;  /* subtle light grey border */
                border-radius: 6px;
                selection-background-color: {GREEN.name()};
            }}
        """)
        layout.addWidget(self.tree, 1)

        self.setStyleSheet(f"""
            QWidget {{
                border-left: 1px solid #DDD;  /* thin separator between columns */
                background-color: {WHITE.name()};
            }}
        """)

    def set_header_color(self, color: QtGui.QColor):
        self.header.setStyleSheet(f"font-weight: 600; font-size: 14px; color: {color.name()};")

    def selected_paths(self):
        return [self.model.filePath(idx) for idx in self.tree.selectionModel().selectedRows(0)]

    def current_dir_for_paste(self, pos: QtCore.QPoint) -> str:
        idx = self.tree.indexAt(pos)
        if idx.isValid() and self.model.isDir(idx):
            return self.model.filePath(idx)
        return self.drive_path

    def open_context_menu(self, pos):
        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: white;
                border: 1px solid #CCC;
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 12px;
                color: #333;
            }}
            QMenu::item:selected {{
                background-color: {GREEN.name()};
                color: white;
            }}
            QMenu::separator {{
                height: 1px;
                background-color: #DDD;
                margin: 4px 8px;
            }}
        """)

        # Add "Open" option for files
        idx = self.tree.indexAt(pos)
        if idx.isValid():
            file_path = self.model.filePath(idx)
            if os.path.isfile(file_path):
                act_open = menu.addAction("Open")
                menu.addSeparator()

        act_copy = menu.addAction("Copy")
        act_move = menu.addAction("Move")
        act_paste_here = menu.addAction("Paste here")
        menu.addSeparator()
        act_new_folder = menu.addAction("New Folder")
        menu.addSeparator()
        act_rename = menu.addAction("Rename")
        act_delete = menu.addAction("Delete")
        menu.addSeparator()
        act_refresh = menu.addAction("Refresh")

        action = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if not action: return

        # Handle "Open" action
        if idx.isValid() and os.path.isfile(self.model.filePath(idx)) and action.text() == "Open":
            file_path = self.model.filePath(idx)
            success = open_file_with_default_app(file_path)
            if not success:
                msg = QtWidgets.QMessageBox(self)
                msg.setWindowTitle("Open File Error")
                msg.setText(
                    f"Could not open file:\n{os.path.basename(file_path)}\n\nThe file may not have an associated application.")
                msg.setIcon(QtWidgets.QMessageBox.Warning)
                msg.setStyleSheet(MESSAGE_BOX_STYLE)
                msg.exec()
        elif action == act_copy:
            paths = self.selected_paths()
            if paths: self.request_copy.emit(paths)
        elif action == act_move:
            paths = self.selected_paths()
            if paths: self.request_move.emit(paths)
        elif action == act_paste_here:
            self.request_paste_here.emit(self.current_dir_for_paste(pos))
        elif action == act_new_folder:
            self.create_new_folder(pos)
        elif action == act_rename:
            idx = self.tree.currentIndex()
            if idx.isValid(): self.tree.edit(idx)
        elif action == act_delete:
            self.delete_selected()
        elif action == act_refresh:
            self.model.refresh()

    def delete_selected(self):
        paths = self.selected_paths()
        if not paths: return
        msg = QtWidgets.QMessageBox(self)
        msg.setWindowTitle("Confirm Delete")
        msg.setText(f"Delete {len(paths)} item(s)? This cannot be undone.")
        msg.setIcon(QtWidgets.QMessageBox.Question)
        msg.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        msg.setDefaultButton(QtWidgets.QMessageBox.No)
        msg.setStyleSheet(MESSAGE_BOX_STYLE)
        reply = msg.exec()
        if reply != QtWidgets.QMessageBox.Yes: return
        errors = []
        for p in paths:
            try:
                if os.path.isdir(p) and not os.path.islink(p):
                    shutil.rmtree(p)
                else:
                    os.remove(p)
            except Exception as e:
                errors.append(f"{p}: {e}")
        if errors:
            error_msg = QtWidgets.QMessageBox(self)
            error_msg.setWindowTitle("Delete Errors")
            error_msg.setText("\n".join(errors))
            error_msg.setIcon(QtWidgets.QMessageBox.Warning)
            error_msg.setStyleSheet(MESSAGE_BOX_STYLE)
            error_msg.exec()
        self.model.refresh()

    def create_new_folder(self, pos):
        """Create a new folder in the appropriate directory"""
        # Determine the target directory
        idx = self.tree.indexAt(pos)
        if idx.isValid() and self.model.isDir(idx):
            target_dir = self.model.filePath(idx)
        else:
            target_dir = self.drive_path

        # Get folder name from user
        dialog = QtWidgets.QInputDialog(self)
        dialog.setWindowTitle("New Folder")
        dialog.setLabelText("Enter folder name:")
        dialog.setTextValue("New Folder")
        dialog.setStyleSheet(MESSAGE_BOX_STYLE)
        ok = dialog.exec()
        text = dialog.textValue()

        if not ok or not text.strip():
            return

        folder_name = text.strip()
        new_folder_path = os.path.join(target_dir, folder_name)

        # Handle name conflicts
        counter = 1
        while os.path.exists(new_folder_path):
            new_folder_path = os.path.join(target_dir, f"{folder_name} ({counter})")
            counter += 1

        try:
            os.makedirs(new_folder_path)
            print(f"Created new folder: {new_folder_path}")

            # Refresh the model to show the new folder
            self.model.refresh()

            # Select and scroll to the new folder after a short delay
            QtCore.QTimer.singleShot(200, lambda: self.select_and_expand_paths([new_folder_path]))

        except Exception as e:
            error_msg = QtWidgets.QMessageBox(self)
            error_msg.setWindowTitle("Create Folder Error")
            error_msg.setText(f"Could not create folder '{folder_name}':\n{str(e)}")
            error_msg.setIcon(QtWidgets.QMessageBox.Warning)
            error_msg.setStyleSheet(MESSAGE_BOX_STYLE)
            error_msg.exec()

    def on_tree_clicked(self, index):
        """Handle tree view clicks to set this panel as active"""
        self.clicked.emit(self)

    def select_and_expand_paths(self, paths):
        """Select and expand to show specific paths"""
        tree = self.tree
        model = self.model
        selection_model = tree.selectionModel()
        selection_model.clearSelection()

        for path in paths:
            if not path or not os.path.exists(path):
                continue

            idx = model.index(path)
            if idx.isValid():
                # Expand all parent directories
                parent = idx.parent()
                while parent.isValid():
                    tree.setExpanded(parent, True)
                    parent = parent.parent()

                # Select the item
                selection_model.select(idx, QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)

                # Scroll to first item
                if path == paths[0]:
                    tree.scrollTo(idx, QtWidgets.QAbstractItemView.PositionAtCenter)


# ---------- File Operation Worker ----------
class FileOperationWorker(QtCore.QRunnable):
    def __init__(self, source_paths, destination_dir, operation):
        super().__init__()
        self.source_paths = source_paths
        self.destination_dir = destination_dir
        self.operation = operation
        self.signals = FileOperationSignals()
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    @QtCore.Slot()
    def run(self):
        if not os.path.isdir(self.destination_dir):
            self.signals.error.emit(f"{self.operation.title()} Error", "Invalid destination directory.")
            return

        errors = []
        success_count = 0
        total_files = len(self.source_paths)

        print(f"Starting {self.operation} operation with {total_files} files")

        for i, source_path in enumerate(self.source_paths):
            if self._is_cancelled:
                print("File operation cancelled")
                break

            try:
                if not os.path.exists(source_path):
                    errors.append(f"{os.path.basename(source_path)}: Source no longer exists")
                    progress_value = int(((i + 1) / total_files) * 100)
                    self.signals.progress.emit(progress_value)
                    continue

                # Check if trying to move/copy to itself or its subdirectory
                try:
                    norm_source = os.path.normpath(source_path)
                    norm_dest = os.path.normpath(self.destination_dir)

                    if norm_source == norm_dest or norm_dest.startswith(norm_source + os.sep):
                        errors.append(
                            f"{os.path.basename(source_path)}: Cannot {self.operation} to itself or subdirectory")
                        progress_value = int(((i + 1) / total_files) * 100)
                        self.signals.progress.emit(progress_value)
                        continue
                except (ValueError, OSError):
                    pass

                filename = os.path.basename(source_path)
                destination_path = os.path.join(self.destination_dir, filename)

                # Handle name conflicts
                counter = 1
                while os.path.exists(destination_path):
                    name, ext = os.path.splitext(filename)
                    if ext:
                        new_filename = f"{name}_copy_{counter}{ext}"
                    else:
                        new_filename = f"{filename}_copy_{counter}"
                    destination_path = os.path.join(self.destination_dir, new_filename)
                    counter += 1

                print(f"  {self.operation}ing: {source_path} -> {destination_path}")

                if self.operation == 'copy':
                    if os.path.isdir(source_path):
                        shutil.copytree(source_path, destination_path, dirs_exist_ok=False)
                    else:
                        shutil.copy2(source_path, destination_path)
                elif self.operation == 'move':
                    shutil.move(source_path, destination_path)

                success_count += 1
                print(f"    Success!")

            except Exception as e:
                error_msg = f"{os.path.basename(source_path)}: {str(e)}"
                errors.append(error_msg)
                print(f"    Error: {error_msg}")

            # Update progress after each file
            progress_value = int(((i + 1) / total_files) * 100)
            self.signals.progress.emit(progress_value)

        # Emit results
        self.signals.result.emit(success_count, errors, self.operation)
        self.signals.finished.emit()


# ---------- File Operation Signals ----------
class FileOperationSignals(QtCore.QObject):
    result = QtCore.Signal(int, list, str)  # success_count, errors, operation
    progress = QtCore.Signal(int)
    error = QtCore.Signal(str, str)  # title, message
    finished = QtCore.Signal()


# ---------- Search Worker ----------
class SearchWorker(QtCore.QRunnable):
    def __init__(self, root_path, query):
        super().__init__()
        self.root_path = root_path
        self.query = query.lower()
        self.signals = WorkerSignals()
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    @QtCore.Slot()
    def run(self):
        matches = []
        processed = 0
        total_processed = 0

        print(f"Starting search for '{self.query}' in {self.root_path}")

        # Normalize the root path to handle different drive formats
        try:
            normalized_root = os.path.normpath(os.path.abspath(self.root_path))
            print(f"Normalized root path: {normalized_root}")
        except Exception as e:
            print(f"Error normalizing root path: {e}")
            normalized_root = self.root_path

        # Check if root path exists and is accessible
        if not os.path.exists(normalized_root) or not os.path.isdir(normalized_root):
            print(f"Root path does not exist or is not accessible: {normalized_root}")
            self.signals.result.emit([])
            self.signals.progress.emit(100)
            self.signals.finished.emit()
            return

        try:
            # Test directory access before starting search
            try:
                test_items = os.listdir(normalized_root)
                print(f"Root directory contains {len(test_items)} items")
            except (PermissionError, OSError) as e:
                print(f"Cannot access root directory: {e}")
                self.signals.result.emit([])
                self.signals.progress.emit(100)
                self.signals.finished.emit()
                return

            for root, dirs, files in os.walk(normalized_root):
                if self._is_cancelled:
                    print("Search cancelled")
                    break

                # Handle permission errors for individual directories
                try:
                    # Verify we can actually access this directory
                    if not os.path.exists(root):
                        continue

                    print(f"Searching in: {root}")

                    # Search in directory names
                    for dir_name in dirs[:]:  # Use slice copy to allow modification
                        if self._is_cancelled:
                            break
                        total_processed += 1

                        try:
                            if self.query in dir_name.lower():
                                full_path = os.path.join(root, dir_name)
                                # Verify the path exists before adding
                                if os.path.exists(full_path):
                                    matches.append(full_path)
                                    print(f"Found directory: {full_path}")
                        except (UnicodeDecodeError, OSError) as e:
                            print(f"Error processing directory name '{dir_name}': {e}")
                            # Remove problematic directories from search
                            dirs.remove(dir_name)
                            continue

                    # Search in file names
                    for file_name in files:
                        if self._is_cancelled:
                            break
                        total_processed += 1

                        try:
                            if self.query in file_name.lower():
                                full_path = os.path.join(root, file_name)
                                # Verify the path exists before adding
                                if os.path.exists(full_path):
                                    matches.append(full_path)
                                    print(f"Found file: {full_path}")
                        except (UnicodeDecodeError, OSError) as e:
                            print(f"Error processing file name '{file_name}': {e}")
                            continue

                except (PermissionError, OSError) as e:
                    print(f"Cannot access directory {root}: {e}")
                    continue

                processed += 1
                # Update progress every 5 directories for more responsive feedback
                if processed % 5 == 0:
                    progress_val = min((processed * 2), 95)
                    self.signals.progress.emit(progress_val)

                # Limit results and directories to prevent endless searching
                if len(matches) > 200 or processed > 2000:
                    print(f"Search limit reached: {len(matches)} matches, {processed} dirs processed")
                    break

        except Exception as e:
            print(f"Search error: {e}")

        print(f"Search completed: {len(matches)} matches found in {processed} directories")
        self.signals.result.emit(matches)
        self.signals.progress.emit(100)
        self.signals.finished.emit()


# ---------- Worker Signals ----------
class WorkerSignals(QtCore.QObject):
    result = QtCore.Signal(list)
    progress = QtCore.Signal(int)
    finished = QtCore.Signal()


# ---------- Main Window ----------
class FileViewer(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ProView - File Manager 1.0")
        self.resize(1400, 800)
        self.showMaximized()  # Open in maximized mode
        self.active_panel = None
        self.thread_pool = QtCore.QThreadPool.globalInstance()

        # Clipboard for copy/move operations
        self.clipboard_paths = []
        self.clipboard_operation = None  # 'copy' or 'move'

        # Search management
        self.current_search_worker = None
        self.search_signals = WorkerSignals()
        self.search_signals.result.connect(self.show_search_results)
        self.search_signals.progress.connect(self.update_progress)
        self.search_signals.finished.connect(self.search_finished)

        # File operation management
        self.current_file_worker = None

        self.apply_flat_palette()
        self.init_ui()

    def apply_flat_palette(self):
        app = QtWidgets.QApplication.instance()
        app.setStyle("Fusion")
        palette = QtGui.QPalette()
        palette.setColor(QtGui.QPalette.Window, WHITE)
        palette.setColor(QtGui.QPalette.Base, WHITE)
        palette.setColor(QtGui.QPalette.AlternateBase, LIGHT_GRAY)
        palette.setColor(QtGui.QPalette.Text, QtGui.QColor(30, 30, 30))
        palette.setColor(QtGui.QPalette.Button, WHITE)
        palette.setColor(QtGui.QPalette.ButtonText, QtGui.QColor(30, 30, 30))
        palette.setColor(QtGui.QPalette.Highlight, DARK_BLUE)
        palette.setColor(QtGui.QPalette.HighlightedText, WHITE)
        app.setPalette(palette)

        # Apply clean scroll bar style globally
        app.setStyleSheet(f"""
            QScrollBar:vertical {{
                background: #F5F5F5;
                width: 12px;
                border: none;
                border-radius: 6px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: #C0C0C0;
                border-radius: 6px;
                min-height: 20px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: #A0A0A0;
            }}
            QScrollBar::handle:vertical:pressed {{
                background: #808080;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                border: none;
                background: none;
                height: 0px;
            }}
            QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical {{
                background: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}

            QScrollBar:horizontal {{
                background: #F5F5F5;
                height: 12px;
                border: none;
                border-radius: 6px;
                margin: 0px;
            }}
            QScrollBar::handle:horizontal {{
                background: #C0C0C0;
                border-radius: 6px;
                min-width: 20px;
                margin: 2px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: #A0A0A0;
            }}
            QScrollBar::handle:horizontal:pressed {{
                background: #808080;
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                border: none;
                background: none;
                width: 0px;
            }}
            QScrollBar::left-arrow:horizontal, QScrollBar::right-arrow:horizontal {{
                background: none;
            }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background: none;
            }}
        """)

    def init_ui(self):
        central = QtWidgets.QWidget(self)
        self.setCentralWidget(central)
        v = QtWidgets.QVBoxLayout(central)

        # Toolbar
        tb = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(tb)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)

        self.btn_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_refresh.setFixedSize(80, 32)
        self.btn_refresh.setStyleSheet(f"""
                    QPushButton {{
                        background: {PURPLE.name()};
                        color: white;
                        font-weight: 600;
                        border-radius: 6px;
                    }}
                    QPushButton:hover {{
                        background: #9b4de0;
                    }}
                """)
        self.btn_refresh.clicked.connect(self.refresh_all)

        # Duplicate finder button
        self.btn_duplicates = QtWidgets.QPushButton("Find Duplicates")
        self.btn_duplicates.setFixedSize(120, 32)
        self.btn_duplicates.clicked.connect(self.show_duplicate_finder)
        self.btn_duplicates.setStyleSheet(f"""
                    QPushButton {{
                        background: #f59e0b;
                        color: white;
                        font-weight: 600;
                        border-radius: 6px;
                    }}
                    QPushButton:hover {{
                        background: #d97706;
                    }}
                """)

        # Drive selection label
        self.drive_label = QtWidgets.QLabel("Please select a drive first")
        self.drive_label.setFixedSize(180, 32)
        self.drive_label.setAlignment(QtCore.Qt.AlignCenter)
        self.drive_label.setStyleSheet(f"""
                    QLabel {{
                        background: {LIGHT_GRAY.name()};
                        border: 1px solid #CCC;
                        border-radius: 6px;
                        padding: 0 12px;
                        font-size: 13px;
                        color: #666;
                        font-style: italic;
                    }}
                """)

        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText("Type to search...")
        self.search_edit.setFixedSize(500, 32)
        self.search_edit.textChanged.connect(self.start_search)
        self.search_edit.setStyleSheet(f"""
                    QLineEdit {{
                        border-radius: 6px;
                        border: 1px solid #CCC;
                        padding-left: 8px;
                        font-size: 13px;
                    }}
                """)

        self.btn_cancel = QtWidgets.QPushButton("Cancel Operation")
        self.btn_cancel.setFixedSize(120, 32)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_operation)
        self.btn_cancel.setStyleSheet(f"""
                    QPushButton {{
                        background: #dc2626;
                        color: white;
                        font-weight: 600;
                        border-radius: 6px;
                    }}
                    QPushButton:hover {{
                        background: #b91c1c;
                    }}
                    QPushButton:disabled {{
                        background: #d1d5db;
                        color: #9ca3af;
                    }}
                """)

        self.btn_about = QtWidgets.QPushButton("🛈")
        self.btn_about.setFixedSize(50, 32)
        self.btn_about.clicked.connect(self.show_about)
        self.btn_about.setStyleSheet(f"""
                    QPushButton {{
                        background: #f5f5f5;
                        color: #cccccc;
                        font-weight: 200;
                        font-size: 20px;
                        border: 0px solid #CCC;
                        border-radius: 6px;
                    }}
                    QPushButton:hover {{
                        background: #f5f5f5;
                    }}
                """)

        h.addWidget(self.btn_refresh)
        h.addWidget(self.btn_duplicates)
        h.addWidget(self.drive_label)
        h.addWidget(self.search_edit, 0)
        h.addWidget(self.btn_cancel)
        h.addStretch(1)
        h.addWidget(self.btn_about)
        v.addWidget(tb)

        # Splitter for drives
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.splitter.setHandleWidth(6)
        v.addWidget(self.splitter, 1)

        # Progress bar
        self.progress = QtWidgets.QProgressBar()
        self.progress.setMaximum(100)
        self.progress.setValue(0)
        self.progress.setFixedHeight(18)
        self.progress.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid #CCC;
                border-radius: 6px;
                background-color: #EEE;
                color: black;
                font-weight: 600;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background-color: {GREEN.name()};
                border-radius: 6px;
            }}
        """)
        v.addWidget(self.progress)

        self.drive_panels = []
        self.populate_drives()

        # Set initial search placeholder
        self.update_search_placeholder()

    def populate_drives(self):
        for panel in self.drive_panels:
            panel.setParent(None)
        self.drive_panels.clear()

        for drive_path, drive_label in list_drives():
            panel = DriveTree(drive_path, drive_label, self)
            panel.clicked.connect(self.set_active_panel)

            # Connect copy/move/paste signals
            panel.request_copy.connect(self.handle_copy)
            panel.request_move.connect(self.handle_move)
            panel.request_paste_here.connect(self.handle_paste)
            panel.file_dropped.connect(self.handle_drag_drop)

            self.splitter.addWidget(panel)
            self.drive_panels.append(panel)

        if self.drive_panels:
            total = self.splitter.size().width() or 1200
            per = int(total / max(1, len(self.drive_panels)))
            self.splitter.setSizes([per] * len(self.drive_panels))

    def set_active_panel(self, panel):
        self.active_panel = panel
        for p in self.drive_panels:
            if p == panel:
                p.set_header_color(GREEN)
            else:
                p.set_header_color(QtGui.QColor('#111'))

        # Update search placeholder based on selected drive
        self.update_search_placeholder()

    def update_search_placeholder(self):
        """Update drive label based on active panel"""
        if self.active_panel:
            drive_letter = self.active_panel.drive_path
            # Extract just the drive letter for cleaner display
            if os.name == "nt" and len(drive_letter) >= 2 and drive_letter[1] == ':':
                drive_display = f"Search in {drive_letter[0]} drive"
            else:
                drive_display = f"Search in {drive_letter}"
            self.drive_label.setText(drive_display)
            self.drive_label.setStyleSheet(f"""
                QLabel {{
                    background: {GREEN.name()};
                    border: 1px solid {GREEN.name()};
                    border-radius: 6px;
                    padding: 0 12px;
                    font-size: 13px;
                    color: white;
                    font-weight: 600;
                }}
            """)
            print(f"Updated drive label to: {drive_display}")
        else:
            self.drive_label.setText("Please select a drive first")
            self.drive_label.setStyleSheet(f"""
                QLabel {{
                    background: {LIGHT_GRAY.name()};
                    border: 1px solid #CCC;
                    border-radius: 6px;
                    padding: 0 12px;
                    font-size: 13px;
                    color: #666;
                    font-style: italic;
                }}
            """)
            print("Updated drive label to: Please select a drive first")

    def handle_copy(self, paths):
        """Handle copy operation"""
        self.clipboard_paths = paths[:]
        self.clipboard_operation = 'copy'
        print(f"Copied {len(paths)} items to clipboard")

    def handle_move(self, paths):
        """Handle move operation"""
        self.clipboard_paths = paths[:]
        self.clipboard_operation = 'move'
        print(f"Cut {len(paths)} items to clipboard")

    def handle_paste(self, destination_dir):
        """Handle paste operation"""
        if not self.clipboard_paths or not self.clipboard_operation:
            msg = QtWidgets.QMessageBox(self)
            msg.setWindowTitle("Paste")
            msg.setText("Nothing to paste. Copy or move some files first.")
            msg.setIcon(QtWidgets.QMessageBox.Information)
            msg.setStyleSheet(MESSAGE_BOX_STYLE)
            msg.exec()
            return

        # Start file operation in a separate thread to show progress
        self.start_file_operation(self.clipboard_paths, destination_dir, self.clipboard_operation)

        # Clear clipboard after move operation
        if self.clipboard_operation == 'move':
            self.clipboard_paths = []
            self.clipboard_operation = None

    def handle_drag_drop(self, source_paths, destination_dir):
        """Handle drag and drop operation"""
        if not source_paths:
            return

        # Filter out invalid paths
        valid_paths = [p for p in source_paths if p and os.path.exists(p)]
        if not valid_paths:
            msg = QtWidgets.QMessageBox(self)
            msg.setWindowTitle("Drag & Drop")
            msg.setText("No valid source files found.")
            msg.setIcon(QtWidgets.QMessageBox.Warning)
            msg.setStyleSheet(MESSAGE_BOX_STYLE)
            msg.exec()
            return

        # Ask user whether to copy or move
        msg = QtWidgets.QMessageBox(self)
        msg.setWindowTitle("Ceyntax | Drag & Drop")
        msg.setText(f"What would you like to do with {len(valid_paths)} item(s)?")
        msg.setIcon(QtWidgets.QMessageBox.Question)
        msg.setStyleSheet(MESSAGE_BOX_STYLE)

        btn_copy = msg.addButton("Copy", QtWidgets.QMessageBox.AcceptRole)
        btn_move = msg.addButton("Move", QtWidgets.QMessageBox.AcceptRole)
        btn_cancel = msg.addButton("Cancel", QtWidgets.QMessageBox.RejectRole)

        result = msg.exec()
        clicked = msg.clickedButton()

        if clicked == btn_copy:
            print(f"User chose to copy {len(valid_paths)} items")
            self.start_file_operation(valid_paths, destination_dir, 'copy')
        elif clicked == btn_move:
            print(f"User chose to move {len(valid_paths)} items")
            self.start_file_operation(valid_paths, destination_dir, 'move')
        else:
            print("User cancelled drag & drop operation")

    def start_file_operation(self, source_paths, destination_dir, operation):
        """Start file operation with progress tracking in separate thread"""
        # Cancel any existing file operation
        if self.current_file_worker:
            self.current_file_worker.cancel()

        # Initialize progress bar
        self.progress.setValue(1)
        self.progress.setFormat(f"{operation.title()}ing files... 0%")
        self.btn_cancel.setEnabled(True)

        # Create and start worker
        self.current_file_worker = FileOperationWorker(source_paths, destination_dir, operation)

        # Connect signals
        self.current_file_worker.signals.progress.connect(self.update_file_progress)
        self.current_file_worker.signals.result.connect(self.handle_file_operation_result)
        self.current_file_worker.signals.error.connect(self.handle_file_operation_error)
        self.current_file_worker.signals.finished.connect(self.file_operation_finished)

        # Start the worker
        self.thread_pool.start(self.current_file_worker)

    def update_file_progress(self, value):
        """Update progress bar for file operations"""
        print(f"Progress update: {value}%")
        self.progress.setValue(value)
        operation = "Copying" if self.current_file_worker and self.current_file_worker.operation == 'copy' else "Moving"
        self.progress.setFormat(f"{operation} files... {value}%")

    def handle_file_operation_result(self, success_count, errors, operation):
        """Handle file operation completion"""
        # Show completion
        self.progress.setValue(100)
        self.progress.setFormat(f"{operation.title()} complete!")

        # Clear progress after delay
        QtCore.QTimer.singleShot(2000, lambda: self.progress.setFormat(""))
        QtCore.QTimer.singleShot(2000, lambda: self.progress.setValue(0))

        # Refresh all panels
        QtCore.QTimer.singleShot(100, self.refresh_all)

        # Show results dialog
        message = f"Successfully {operation}ed {success_count} item(s)."
        if errors:
            message += f"\n\nErrors:\n" + "\n".join(errors[:3])
            if len(errors) > 3:
                message += f"\n... and {len(errors) - 3} more errors."

        msg = QtWidgets.QMessageBox(self)
        if errors and success_count == 0:
            msg.setWindowTitle(f"{operation.title()} Failed")
            msg.setIcon(QtWidgets.QMessageBox.Critical)
        elif errors:
            msg.setWindowTitle(f"{operation.title()} Results")
            msg.setIcon(QtWidgets.QMessageBox.Warning)
        else:
            msg.setWindowTitle(f"{operation.title()} Complete")
            msg.setIcon(QtWidgets.QMessageBox.Information)

        msg.setText(message)
        msg.setStyleSheet(MESSAGE_BOX_STYLE)
        msg.exec()

    def handle_file_operation_error(self, title, message):
        """Handle file operation errors"""
        msg = QtWidgets.QMessageBox(self)
        msg.setWindowTitle(title)
        msg.setText(message)
        msg.setIcon(QtWidgets.QMessageBox.Warning)
        msg.setStyleSheet(MESSAGE_BOX_STYLE)
        msg.exec()

    def file_operation_finished(self):
        """Called when file operation worker finishes"""
        print("File operation worker finished")
        self.current_file_worker = None
        self.btn_cancel.setEnabled(False)

    def refresh_all(self):
        for panel in self.drive_panels:
            panel.model.refresh()

    def start_search(self):
        # Cancel previous search if running
        if self.current_search_worker:
            self.current_search_worker.cancel()

        query = self.search_edit.text().strip()
        if not query:
            # Clear search results when query is empty
            if self.active_panel:
                self.active_panel.tree.selectionModel().clearSelection()
            self.progress.setValue(0)
            self.progress.setFormat("")
            self.btn_cancel.setEnabled(False)
            return

        if not self.active_panel:
            print("No active panel selected for search")
            return

        if len(query) < 2:
            return

        print(f"Starting search for: '{query}' in {self.active_panel.drive_path}")

        # Clear previous results and reset progress
        self.active_panel.tree.selectionModel().clearSelection()
        self.progress.setValue(0)
        self.progress.setFormat("Searching... 0%")
        self.btn_cancel.setEnabled(True)

        # Create new search worker with fresh signals
        self.current_search_worker = SearchWorker(self.active_panel.drive_path, query)

        # Connect signals directly to this worker
        self.current_search_worker.signals.result.connect(self.show_search_results)
        self.current_search_worker.signals.progress.connect(self.update_progress)
        self.current_search_worker.signals.finished.connect(self.search_finished)

        self.thread_pool.start(self.current_search_worker)

    def update_progress(self, value):
        """Update progress bar with searching text and percentage"""
        self.progress.setValue(value)
        self.progress.setFormat(f"Searching... {value}%")

    def cancel_operation(self):
        """Cancel current search or file operation"""
        cancelled_something = False

        if self.current_search_worker:
            print("Cancelling search operation")
            self.current_search_worker.cancel()
            self.current_search_worker = None
            cancelled_something = True

        if self.current_file_worker:
            print("Cancelling file operation")
            self.current_file_worker.cancel()
            self.current_file_worker = None
            cancelled_something = True

        if cancelled_something:
            # Reset progress bar
            self.progress.setValue(0)
            self.progress.setFormat("")
            self.btn_cancel.setEnabled(False)
            print("Operation cancelled by user")

    def search_finished(self):
        """Called when search is finished"""
        print("Search worker finished")
        self.current_search_worker = None
        self.btn_cancel.setEnabled(False)

    def show_search_results(self, paths):
        """Display search results by selecting and expanding to found items"""
        if not self.active_panel or not paths:
            if not paths:
                print("No matching items found")
            return

        print(f"Found {len(paths)} matching items")

        # Use the panel's method to select and expand paths
        self.active_panel.select_and_expand_paths(paths)

    def show_about(self):
        """Show About dialog"""
        about_dialog = QtWidgets.QMessageBox(self)
        about_dialog.setWindowTitle("About ProView")
        about_dialog.setText("""
    <h3>ProView 1.0</h3>
    <p>A modern multi-panel file manager</p>
    <p><b>Features:</b></p>
    <ul>
    <li>Multi-drive support with drag & drop</li>
    <li>Real-time search across drives</li>
    <li>Copy/Move operations with progress tracking</li>
    <li>Double-click to open files</li>
    <li>Duplicate file finder</li>
    </ul>
    <li>Developed by Ceyntax Technologies</li>
    <li>www.ceyntax.com</li>
        """)
        about_dialog.setIcon(QtWidgets.QMessageBox.Information)
        about_dialog.setStandardButtons(QtWidgets.QMessageBox.Ok)
        about_dialog.setStyleSheet(MESSAGE_BOX_STYLE)
        about_dialog.exec()

    def show_duplicate_finder(self):
        """Show the duplicate file finder dialog"""
        dialog = DuplicateFilesDialog(self, list_drives)
        dialog.exec()


# ---------- Run ----------
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    viewer = FileViewer()
    viewer.show()
    sys.exit(app.exec())