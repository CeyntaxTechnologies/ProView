import os
import hashlib
from collections import defaultdict
from datetime import datetime
from PySide6 import QtCore, QtGui, QtWidgets

# Message box styling
MESSAGE_BOX_STYLE = """
    QMessageBox {
        background-color: white;
    }
    QMessageBox QLabel {
        color: black;
    }
"""


# ---------- Duplicate Finder Worker ----------
class DuplicateFinderWorker(QtCore.QRunnable):
    def __init__(self, root_paths, min_file_size=0):
        super().__init__()
        self.root_paths = root_paths
        self.min_file_size = min_file_size  # Skip files smaller than this (in bytes)
        self.signals = DuplicateFinderSignals()
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def get_file_hash(self, filepath, chunk_size=8192):
        """Calculate MD5 hash of a file"""
        hash_md5 = hashlib.md5()
        try:
            with open(filepath, "rb") as f:
                while chunk := f.read(chunk_size):
                    if self._is_cancelled:
                        return None
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except (IOError, OSError, PermissionError) as e:
            print(f"Error reading file {filepath}: {e}")
            return None

    @QtCore.Slot()
    def run(self):
        print(f"Starting duplicate search in {len(self.root_paths)} paths")
        print(f"Root paths: {self.root_paths}")

        # Dictionary to store files by size first (quick pre-filter)
        size_groups = defaultdict(list)
        total_files = 0
        processed_files = 0

        # Step 1: Group files by size
        self.signals.status.emit("Scanning files...")
        print("Step 1: Scanning files...")

        for root_path in self.root_paths:
            if self._is_cancelled:
                print("Cancelled during file scanning")
                break

            print(f"Scanning root path: {root_path}")

            # Verify root path exists
            if not os.path.exists(root_path):
                print(f"Root path does not exist: {root_path}")
                continue

            if not os.path.isdir(root_path):
                print(f"Root path is not a directory: {root_path}")
                continue

            try:
                # Test if we can list the directory
                try:
                    test_list = os.listdir(root_path)
                    print(f"Root directory {root_path} contains {len(test_list)} items")
                except (PermissionError, OSError) as e:
                    print(f"Cannot access root directory {root_path}: {e}")
                    self.signals.status.emit(f"Cannot access {root_path}: {e}")
                    continue

                for root, dirs, files in os.walk(root_path):
                    if self._is_cancelled:
                        print("Cancelled during directory walk")
                        break

                    print(f"Processing directory: {root} ({len(files)} files)")

                    for filename in files:
                        if self._is_cancelled:
                            break

                        filepath = os.path.join(root, filename)
                        try:
                            # Check if file exists and is accessible
                            if not os.path.exists(filepath):
                                continue

                            if os.path.islink(filepath):
                                continue  # Skip symbolic links

                            stat_info = os.stat(filepath)
                            file_size = stat_info.st_size

                            # Skip small files if minimum size is set
                            if file_size < self.min_file_size:
                                continue

                            size_groups[file_size].append(filepath)
                            total_files += 1

                            if total_files % 50 == 0:
                                status_msg = f"Scanned {total_files} files..."
                                self.signals.status.emit(status_msg)
                                print(status_msg)

                        except (OSError, PermissionError) as e:
                            print(f"Error accessing file {filepath}: {e}")
                            continue

            except Exception as e:
                print(f"Error scanning {root_path}: {e}")
                self.signals.status.emit(f"Error scanning {root_path}: {e}")
                continue

        if self._is_cancelled:
            print("Scan was cancelled")
            self.signals.finished.emit()
            return

        print(f"Found {total_files} files in {len(size_groups)} size groups")
        self.signals.status.emit(f"Found {total_files} files, checking for duplicates...")

        # Step 2: Calculate hashes for files with same size
        hash_groups = defaultdict(list)
        potential_duplicates = 0

        # Count potential duplicates
        for file_size, file_paths in size_groups.items():
            if len(file_paths) > 1:  # Only check files that have same-sized siblings
                potential_duplicates += len(file_paths)

        print(f"Found {potential_duplicates} potential duplicate files")

        if potential_duplicates == 0:
            print("No potential duplicates found")
            self.signals.result.emit([], 0)
            self.signals.progress.emit(100)
            self.signals.finished.emit()
            return

        self.signals.status.emit(f"Checking {potential_duplicates} potential duplicates...")

        for file_size, file_paths in size_groups.items():
            if self._is_cancelled:
                break

            if len(file_paths) > 1:  # Only hash files with same-sized siblings
                print(f"Hashing {len(file_paths)} files of size {file_size} bytes")

                for filepath in file_paths:
                    if self._is_cancelled:
                        break

                    file_hash = self.get_file_hash(filepath)
                    if file_hash:
                        hash_groups[file_hash].append(filepath)

                    processed_files += 1
                    if processed_files % 10 == 0:
                        progress = int((processed_files / potential_duplicates) * 100)
                        self.signals.progress.emit(progress)

        if self._is_cancelled:
            print("Cancelled during hash calculation")
            self.signals.finished.emit()
            return

        # Step 3: Filter out unique files and organize duplicates
        duplicate_groups = []
        total_duplicate_files = 0
        total_wasted_space = 0

        print(f"Processing {len(hash_groups)} hash groups")

        for file_hash, file_paths in hash_groups.items():
            if len(file_paths) > 1:
                print(f"Found duplicate group with {len(file_paths)} files")

                # Sort by modification time (keep oldest by default)
                try:
                    file_paths.sort(key=lambda x: os.path.getmtime(x))
                except (OSError, PermissionError):
                    # If we can't get modification times, just keep the original order
                    pass

                try:
                    file_size = os.path.getsize(file_paths[0])
                    wasted_space = file_size * (len(file_paths) - 1)

                    duplicate_groups.append({
                        'hash': file_hash,
                        'files': file_paths,
                        'size': file_size,
                        'wasted_space': wasted_space,
                        'count': len(file_paths)
                    })

                    total_duplicate_files += len(file_paths) - 1  # Subtract one original
                    total_wasted_space += wasted_space
                except (OSError, PermissionError) as e:
                    print(f"Error getting file size for duplicate group: {e}")
                    continue

        print(f"Found {len(duplicate_groups)} duplicate groups with {total_duplicate_files} duplicate files")
        print(f"Total wasted space: {total_wasted_space / (1024 * 1024):.2f} MB")

        self.signals.result.emit(duplicate_groups, total_wasted_space)
        self.signals.progress.emit(100)
        self.signals.finished.emit()


# ---------- Duplicate Finder Signals ----------
class DuplicateFinderSignals(QtCore.QObject):
    result = QtCore.Signal(list, int)  # duplicate_groups, total_wasted_space
    progress = QtCore.Signal(int)
    status = QtCore.Signal(str)
    finished = QtCore.Signal()


# ---------- Duplicate Files Dialog ----------
class DuplicateFilesDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, list_drives_func=None):
        super().__init__(parent)
        self.setWindowTitle("Duplicate File Finder")
        self.setMinimumSize(900, 600)
        self.duplicate_groups = []
        self.current_worker = None
        self.list_drives_func = list_drives_func  # Function to get available drives

        self.init_ui()

    def init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # Set dialog style for dark grey text
        self.setStyleSheet("""
            QDialog {
                background-color: white;
                color: #333333;
            }
            QLabel {
                color: #333333;
            }
            QGroupBox {
                color: #333333;
                font-weight: bold;
            }
            QCheckBox {
                color: #333333;
            }
            QTreeWidget {
                color: #333333;
            }
        """)

        # Settings section
        settings_group = QtWidgets.QGroupBox("Search Settings")
        settings_layout = QtWidgets.QVBoxLayout(settings_group)

        # Drive selection
        drive_layout = QtWidgets.QHBoxLayout()
        drive_layout.addWidget(QtWidgets.QLabel("Search in drives:"))

        self.drive_checkboxes = {}
        if self.list_drives_func:
            for drive_path, drive_label in self.list_drives_func():
                checkbox = QtWidgets.QCheckBox(drive_label)
                checkbox.setChecked(True)  # Check all drives by default
                self.drive_checkboxes[drive_path] = checkbox
                drive_layout.addWidget(checkbox)
        else:
            # Fallback if no function provided
            label = QtWidgets.QLabel("No drives available")
            drive_layout.addWidget(label)

        settings_layout.addLayout(drive_layout)

        # Minimum file size
        size_layout = QtWidgets.QHBoxLayout()
        size_layout.addWidget(QtWidgets.QLabel("Minimum file size (KB):"))
        self.size_spinbox = QtWidgets.QSpinBox()
        self.size_spinbox.setRange(0, 999999)
        self.size_spinbox.setValue(1)  # Default 1KB
        self.size_spinbox.setSuffix(" KB")
        size_layout.addWidget(self.size_spinbox)
        size_layout.addStretch()
        settings_layout.addLayout(size_layout)

        layout.addWidget(settings_group)

        # Control buttons
        button_layout = QtWidgets.QHBoxLayout()

        self.scan_button = QtWidgets.QPushButton("Start Scan")
        self.scan_button.clicked.connect(self.start_scan)
        self.scan_button.setStyleSheet("""
            QPushButton {
                background: #10b981;
                color: white;
                font-weight: 600;
                padding: 8px 16px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background: #059669;
            }
        """)

        self.cancel_button = QtWidgets.QPushButton("Cancel Scan")
        self.cancel_button.clicked.connect(self.cancel_scan)
        self.cancel_button.setEnabled(False)
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background: #dc2626;
                color: white;
                font-weight: 600;
                padding: 8px 16px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background: #b91c1c;
            }
            QPushButton:disabled {
                background: #d1d5db;
                color: #9ca3af;
            }
        """)

        button_layout.addWidget(self.scan_button)
        button_layout.addWidget(self.cancel_button)
        button_layout.addStretch()

        layout.addLayout(button_layout)

        # Progress and status
        self.status_label = QtWidgets.QLabel("Ready to scan")
        layout.addWidget(self.status_label)

        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Results section
        self.results_widget = QtWidgets.QWidget()
        results_layout = QtWidgets.QVBoxLayout(self.results_widget)

        # Summary
        self.summary_label = QtWidgets.QLabel()
        self.summary_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #333;")
        results_layout.addWidget(self.summary_label)

        # Duplicate files tree
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["File Path", "Size", "Modified", "Action"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        results_layout.addWidget(self.tree)

        # Action buttons for results
        action_layout = QtWidgets.QHBoxLayout()

        self.select_all_duplicates = QtWidgets.QPushButton("Select All Duplicates")
        self.select_all_duplicates.clicked.connect(self.select_duplicates)

        self.delete_selected = QtWidgets.QPushButton("Delete Selected")
        self.delete_selected.clicked.connect(self.delete_selected_files)
        self.delete_selected.setStyleSheet("""
            QPushButton {
                background: #dc2626;
                color: white;
                font-weight: 600;
                padding: 6px 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background: #b91c1c;
            }
        """)

        action_layout.addWidget(self.select_all_duplicates)
        action_layout.addWidget(self.delete_selected)
        action_layout.addStretch()

        results_layout.addLayout(action_layout)

        self.results_widget.setVisible(False)
        layout.addWidget(self.results_widget)

        # Thread pool for background operations
        self.thread_pool = QtCore.QThreadPool.globalInstance()

    def start_scan(self):
        # Get selected drives
        selected_drives = []
        for drive_path, checkbox in self.drive_checkboxes.items():
            if checkbox.isChecked():
                selected_drives.append(drive_path)

        if not selected_drives:
            msg = QtWidgets.QMessageBox(self)
            msg.setWindowTitle("No Drives Selected")
            msg.setText("Please select at least one drive to scan.")
            msg.setIcon(QtWidgets.QMessageBox.Warning)
            msg.setStyleSheet(MESSAGE_BOX_STYLE)
            msg.exec()
            return

        # Get minimum file size in bytes
        min_size_kb = self.size_spinbox.value()
        min_size_bytes = min_size_kb * 1024

        # Update UI
        self.scan_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.results_widget.setVisible(False)

        # Start worker
        self.current_worker = DuplicateFinderWorker(selected_drives, min_size_bytes)
        self.current_worker.signals.progress.connect(self.update_progress)
        self.current_worker.signals.status.connect(self.update_status)
        self.current_worker.signals.result.connect(self.show_results)
        self.current_worker.signals.finished.connect(self.scan_finished)

        self.thread_pool.start(self.current_worker)

    def cancel_scan(self):
        if self.current_worker:
            self.current_worker.cancel()
            self.update_status("Cancelling scan...")

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def update_status(self, message):
        self.status_label.setText(message)

    def show_results(self, duplicate_groups, total_wasted_space):
        self.duplicate_groups = duplicate_groups

        if not duplicate_groups:
            self.summary_label.setText("No duplicate files found!")
            self.results_widget.setVisible(True)
            return

        # Update summary
        total_duplicates = sum(group['count'] - 1 for group in duplicate_groups)
        wasted_mb = total_wasted_space / (1024 * 1024)
        self.summary_label.setText(
            f"Found {len(duplicate_groups)} duplicate groups with {total_duplicates} duplicate files\n"
            f"Total wasted space: {wasted_mb:.2f} MB"
        )

        # Populate tree
        self.tree.clear()

        for group in duplicate_groups:
            # Create group item
            group_item = QtWidgets.QTreeWidgetItem(self.tree)
            group_item.setText(0, f"Duplicate Group ({group['count']} files)")
            group_item.setText(1, f"{group['size'] / 1024:.1f} KB")
            group_item.setText(2, f"Wasted: {group['wasted_space'] / 1024:.1f} KB")
            group_item.setBackground(0, QtGui.QColor(240, 240, 240))

            # Add file items
            for i, filepath in enumerate(group['files']):
                file_item = QtWidgets.QTreeWidgetItem(group_item)
                file_item.setText(0, filepath)
                file_item.setText(1, f"{group['size'] / 1024:.1f} KB")

                try:
                    mtime = os.path.getmtime(filepath)
                    mod_time = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
                    file_item.setText(2, mod_time)
                except:
                    file_item.setText(2, "Unknown")

                # Mark duplicates (all except first/oldest)
                if i == 0:
                    file_item.setText(3, "Keep (Original)")
                    file_item.setBackground(0, QtGui.QColor(200, 255, 200))
                else:
                    file_item.setText(3, "Duplicate")
                    file_item.setBackground(0, QtGui.QColor(255, 220, 220))
                    file_item.setCheckState(0, QtCore.Qt.Unchecked)

        self.tree.expandAll()
        self.results_widget.setVisible(True)

    def select_duplicates(self):
        """Select all duplicate files (not originals)"""
        iterator = QtWidgets.QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            item = iterator.value()
            if item.text(3) == "Duplicate":
                item.setCheckState(0, QtCore.Qt.Checked)
            iterator += 1

    def delete_selected_files(self):
        """Delete checked files"""
        files_to_delete = []

        iterator = QtWidgets.QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            item = iterator.value()
            if item.checkState(0) == QtCore.Qt.Checked and item.text(3) == "Duplicate":
                files_to_delete.append(item.text(0))
            iterator += 1

        if not files_to_delete:
            msg = QtWidgets.QMessageBox(self)
            msg.setWindowTitle("No Files Selected")
            msg.setText("Please select files to delete by checking the boxes.")
            msg.setIcon(QtWidgets.QMessageBox.Information)
            msg.setStyleSheet(MESSAGE_BOX_STYLE)
            msg.exec()
            return

        # Confirm deletion
        msg = QtWidgets.QMessageBox(self)
        msg.setWindowTitle("Confirm Deletion")
        msg.setText(
            f"Are you sure you want to delete {len(files_to_delete)} duplicate files?\n\nThis action cannot be undone!")
        msg.setIcon(QtWidgets.QMessageBox.Warning)
        msg.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        msg.setDefaultButton(QtWidgets.QMessageBox.No)
        msg.setStyleSheet(MESSAGE_BOX_STYLE)

        if msg.exec() != QtWidgets.QMessageBox.Yes:
            return

        # Delete files
        deleted_count = 0
        errors = []

        for filepath in files_to_delete:
            try:
                os.remove(filepath)
                deleted_count += 1
                print(f"Deleted: {filepath}")
            except Exception as e:
                errors.append(f"{os.path.basename(filepath)}: {str(e)}")
                print(f"Error deleting {filepath}: {e}")

        # Show results
        if errors:
            error_msg = QtWidgets.QMessageBox(self)
            error_msg.setWindowTitle("Deletion Results")
            error_msg.setText(f"Successfully deleted {deleted_count} files.\n\nErrors:\n" + "\n".join(errors[:5]))
            error_msg.setIcon(QtWidgets.QMessageBox.Warning)
            error_msg.setStyleSheet(MESSAGE_BOX_STYLE)
            error_msg.exec()
        else:
            success_msg = QtWidgets.QMessageBox(self)
            success_msg.setWindowTitle("Deletion Complete")
            success_msg.setText(f"Successfully deleted {deleted_count} duplicate files!")
            success_msg.setIcon(QtWidgets.QMessageBox.Information)
            success_msg.setStyleSheet(MESSAGE_BOX_STYLE)
            success_msg.exec()

        # Refresh results
        self.start_scan()

    def scan_finished(self):
        self.scan_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.current_worker = None
        self.status_label.setText("Scan completed")