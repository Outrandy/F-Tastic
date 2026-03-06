import sys
import os
import socket
import threading
import shutil
import json
import time
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLineEdit, QPushButton, QTreeWidget, 
                             QTreeWidgetItem, QFileDialog, QLabel, QMenu, QFrame,
                             QProgressBar, QScrollArea, QStackedWidget, QProgressDialog,
                             QHeaderView, QSplitter, QMessageBox)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QObject, QMimeData, QUrl, QTimer
from PyQt6.QtGui import QIcon, QAction, QDrag, QCursor
from zeroconf import ServiceInfo, Zeroconf, ServiceBrowser, ServiceListener

# --- 2026 Theme Constants ---
COLOR_TEAL = "#008080"
COLOR_LIGHT_TEAL = "#20B2AA"
COLOR_BG_WHITE = "#FFFFFF"
COLOR_GREY_LIGHT = "#F8F9FA"
COLOR_GREY_BORDER = "#D1D5DB"
COLOR_TEXT_DARK = "#1F2937"
COLOR_DARK_GREY = "#6B7280"
COLOR_GREY_PRESSED = "#D1D5DB"

# Files to ignore in the UI
IGNORE_LIST = ["desktop.ini", "thumbs.db", ".ds_store", "$recycle.bin", "system volume information"]

def format_size(size_bytes):
    if size_bytes == 0: return "0 B"
    units = ("B", "KB", "MB", "GB", "TB")
    i = 0
    while size_bytes >= 1000 and i < len(units) - 1:
        size_bytes /= 1024.0
        i += 1
    return f"{size_bytes:.1f} {units[i]}"

def get_folder_size(path):
    total = 0
    try:
        for entry in os.scandir(path):
            if entry.name.lower() in IGNORE_LIST: continue
            if entry.is_file():
                total += entry.stat().st_size
            elif entry.is_dir():
                total += get_folder_size(entry.path)
    except: pass
    return total

class Communicate(QObject):
    peer_discovered = pyqtSignal(str, str)
    remote_list_received = pyqtSignal(list, str, QTreeWidgetItem)
    download_progress = pyqtSignal(int)
    download_finished = pyqtSignal(str, str)
    refresh_complete = pyqtSignal()
    transfer_status_changed = pyqtSignal(str, str, bool, str) # IP, ArrowType, IsActive, FileName

class MyListener(ServiceListener):
    def __init__(self, trigger_signal):
        self.trigger_signal = trigger_signal

    def add_service(self, zc, type_, name):
        info = zc.get_service_info(type_, name)
        if info and info.addresses:
            address = socket.inet_ntoa(info.addresses[0])
            if address != socket.gethostbyname(socket.gethostname()):
                self.trigger_signal.emit(address, name.split('.')[0])

    def update_service(self, zc, type_, name): pass
    def remove_service(self, zc, type_, name): pass

class DraggableTree(QTreeWidget):
    def mouseMoveEvent(self, event):
        item = self.itemAt(event.pos())
        if item and (event.buttons() & Qt.MouseButton.LeftButton):
            path = item.data(0, Qt.ItemDataRole.UserRole)
            if path and not str(path).startswith("REMOTE:") and os.path.exists(path):
                drag = QDrag(self)
                mime = QMimeData()
                mime.setUrls([QUrl.fromLocalFile(path)])
                drag.setMimeData(mime)
                drag.exec(Qt.DropAction.CopyAction)
        super().mouseMoveEvent(event)

class FTasticApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("F-Tastic")
        self.resize(1200, 800)
        self.shared_folder_path = None
        self.peers = {} 
        self.current_remote_ip = None
        self.current_remote_name = ""
        self.zc = None
        self.browser = None
        self.is_downloading = False
        
        self.comm = Communicate()
        self.comm.peer_discovered.connect(self.add_peer_to_ui)
        self.comm.remote_list_received.connect(self.populate_remote_view)
        self.comm.download_progress.connect(self.update_dl_dialog)
        self.comm.download_finished.connect(self.finalize_dl)
        self.comm.refresh_complete.connect(self.reset_refresh_button)
        self.comm.transfer_status_changed.connect(self.toggle_blink_timer)

        self.blink_timer = QTimer()
        self.blink_timer.timeout.connect(self.update_blinks)
        self.active_blinks = {} # {IP: {"arrow": ArrowChar, "file": FileName}}
        self.blink_state = True

        self.init_ui()
        self.init_mdns()
        self.start_server()

    def closeEvent(self, event):
        if self.active_blinks:
            for ip, data in self.active_blinks.items():
                peer_name = self.peers[ip].text(0).split("  ")[0] if ip in self.peers else ip
                file_name = data["file"]
                msg = f"{peer_name} is downloading {file_name} from you, they will lose connection, and download will cancel if you close this window. Would you like to continue?"
                if data["arrow"] == "◀":
                    msg = f"You are downloading {file_name} from {peer_name}. You will lose connection and the download will cancel if you close this window. Would you like to continue?"
                
                reply = QMessageBox.question(self, 'Active Transfer', msg, QMessageBox.StandardButton.Close | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
                if reply == QMessageBox.StandardButton.Close: event.accept()
                else: event.ignore(); return
        event.accept()

    def get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except: return socket.gethostbyname(socket.gethostname())

    def init_ui(self):
        main_widget = QWidget()
        main_widget.setStyleSheet(f"background-color: {COLOR_BG_WHITE}; color: {COLOR_TEXT_DARK}; font-family: 'Segoe UI';")
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 0)

        top_bar = QHBoxLayout()
        self.ip_input = QLineEdit(); self.ip_input.setPlaceholderText("Enter Local IP..."); self.ip_input.setFixedWidth(150); self.ip_input.setStyleSheet(f"padding: 8px; border: 1px solid {COLOR_GREY_BORDER}; border-radius: 4px;"); self.ip_input.returnPressed.connect(self.add_manual_ip)
        self.nick_input = QLineEdit(); self.nick_input.setPlaceholderText("Nickname"); self.nick_input.setFixedWidth(240); self.nick_input.setStyleSheet(f"padding: 8px; border: 1px solid {COLOR_GREY_BORDER}; border-radius: 4px;"); self.nick_input.returnPressed.connect(self.add_manual_ip)
        
        add_btn = QPushButton("+"); add_btn.setStyleSheet(f"background-color: {COLOR_TEAL}; color: white; font-weight: bold; padding: 8px 15px; border-radius: 4px;"); add_btn.clicked.connect(self.add_manual_ip)
        self.refresh_btn = QPushButton("Refresh"); self.refresh_btn.setStyleSheet(f"background-color: {COLOR_GREY_LIGHT}; border: 1px solid {COLOR_GREY_BORDER}; padding: 8px 15px; border-radius: 4px;"); self.refresh_btn.clicked.connect(self.trigger_refresh)
        link_btn = QPushButton("Link Shared Folder"); link_btn.setStyleSheet(f"background-color: {COLOR_LIGHT_TEAL}; color: white; padding: 8px 15px; border-radius: 4px; font-weight: 600;"); link_btn.clicked.connect(self.link_folder)
        
        top_bar.addWidget(self.ip_input); top_bar.addWidget(self.nick_input); top_bar.addWidget(add_btn); top_bar.addStretch(); top_bar.addWidget(self.refresh_btn); top_bar.addWidget(link_btn)
        layout.addLayout(top_bar)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(4)
        
        self.nav_pane = QTreeWidget(); self.nav_pane.setHeaderLabel("Locations"); self.nav_pane.setStyleSheet(f"background-color: {COLOR_GREY_LIGHT}; border: none; border-right: 1px solid {COLOR_GREY_BORDER};")
        self.nav_pane.setMinimumWidth(150)
        self.root_net = QTreeWidgetItem(self.nav_pane, ["Network Peers"]); self.root_manual = QTreeWidgetItem(self.nav_pane, ["Manual IPs"]); self.nav_pane.expandAll(); self.nav_pane.itemClicked.connect(self.on_nav_item_clicked)
        
        self.file_tree = DraggableTree(); self.file_tree.setColumnCount(5); self.file_tree.setHeaderLabels(["Name", "Size", "Type", "Date Modified", "Location"]); self.file_tree.setSortingEnabled(True); self.file_tree.setAlternatingRowColors(True); self.file_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); self.file_tree.customContextMenuRequested.connect(self.show_file_context_menu); self.file_tree.itemExpanded.connect(self.on_tree_item_expanded)
        header = self.file_tree.header(); header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.file_tree.setColumnWidth(1, 120); self.file_tree.setColumnWidth(2, 100); self.file_tree.setColumnWidth(3, 150); self.file_tree.setColumnWidth(4, 150)
        
        self.splitter.addWidget(self.nav_pane)
        self.splitter.addWidget(self.file_tree)
        self.splitter.setStretchFactor(0, 0); self.splitter.setStretchFactor(1, 1); self.splitter.setSizes([300, 900])
        layout.addWidget(self.splitter, 1)

        footer_widget = QFrame(); footer_widget.setFixedHeight(30); footer_layout = QHBoxLayout(footer_widget); footer_layout.setContentsMargins(5, 0, 5, 0)
        self.status_lbl = QLabel("Ready"); footer_layout.addWidget(self.status_lbl); footer_layout.addStretch()
        version_lbl = QLabel("Version 1.0 - Randy Brown 2026"); version_lbl.setStyleSheet(f"color: {COLOR_DARK_GREY}; font-weight: bold; font-size: 10px;"); footer_layout.addWidget(version_lbl)
        layout.addWidget(footer_widget)

    def toggle_blink_timer(self, ip, arrow, active, filename):
        if active:
            self.active_blinks[ip] = {"arrow": arrow, "file": filename}
            if not self.blink_timer.isActive(): self.blink_timer.start(500)
        else:
            if ip in self.active_blinks:
                del self.active_blinks[ip]
                if ip in self.peers:
                    item = self.peers[ip]; name = item.text(0).split("  ")[0]
                    item.setText(0, name); item.setForeground(0, Qt.GlobalColor.black)
            if not self.active_blinks: self.blink_timer.stop()

    def update_blinks(self):
        self.blink_state = not self.blink_state
        for ip, data in self.active_blinks.items():
            if ip in self.peers:
                item = self.peers[ip]; base_name = item.text(0).split("  ")[0]
                if self.blink_state:
                    item.setText(0, f"{base_name}  {data['arrow']}")
                    item.setForeground(0, Qt.GlobalColor.darkCyan)
                else: item.setText(0, base_name)

    def trigger_refresh(self):
        self.refresh_btn.setText("Refreshing..."); self.refresh_btn.setEnabled(False)
        def run_refresh():
            if self.current_remote_ip: self.request_remote_list(self.current_remote_ip)
            elif self.shared_folder_path: self.refresh_file_view(self.shared_folder_path)
            time.sleep(0.3); self.comm.refresh_complete.emit()
        threading.Thread(target=run_refresh, daemon=True).start()

    def reset_refresh_button(self):
        self.refresh_btn.setText("Refresh"); self.refresh_btn.setEnabled(True)

    def link_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select Shared Folder")
        if path: self.shared_folder_path = path; self.refresh_file_view(path)

    def refresh_file_view(self, target_path):
        self.file_tree.clear()
        folder_name = os.path.basename(target_path) or target_path
        size = format_size(get_folder_size(target_path))
        root_item = QTreeWidgetItem(self.file_tree, [folder_name, size, "Folder", "--", "Local"])
        root_item.setData(0, Qt.ItemDataRole.UserRole, target_path)
        root_item.setIcon(0, self.style().standardIcon(self.style().StandardPixmap.SP_DirIcon))
        root_item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator); root_item.setExpanded(True)
        self.add_local_items(target_path, root_item)

    def add_local_items(self, path, parent_item):
        if not os.path.exists(path): return
        try:
            for item in os.listdir(path):
                if item.lower() in IGNORE_LIST: continue
                full_path = os.path.join(path, item); is_dir = os.path.isdir(full_path)
                raw_size = get_folder_size(full_path) if is_dir else os.path.getsize(full_path)
                size_str = format_size(raw_size)
                date_str = datetime.fromtimestamp(os.path.getmtime(full_path)).strftime('%Y-%m-%d %H:%M')
                t_item = QTreeWidgetItem(parent_item, [item, size_str, "Folder" if is_dir else "File", date_str, "Local"])
                t_item.setData(0, Qt.ItemDataRole.UserRole, full_path)
                t_item.setIcon(0, self.style().standardIcon(self.style().StandardPixmap.SP_DirIcon if is_dir else self.style().StandardPixmap.SP_FileIcon))
                if is_dir: t_item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        except: pass

    def on_tree_item_expanded(self, item):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path: return
        if not str(path).startswith("REMOTE:") and os.path.isdir(path):
            if item.childCount() == 0: self.add_local_items(path, item)
        elif str(path).startswith("REMOTE:"):
            if item.childCount() == 0:
                rel_path = str(path).replace("REMOTE:", "")
                threading.Thread(target=self.request_remote_list, args=(self.current_remote_ip, rel_path, item), daemon=True).start()

    def on_nav_item_clicked(self, item, col):
        ip = item.data(0, Qt.ItemDataRole.UserRole)
        if ip: 
            self.current_remote_ip = ip; self.current_remote_name = item.text(0).split("  ")[0].split(" (")[0]
            threading.Thread(target=self.request_remote_list, args=(ip,), daemon=True).start()

    def request_remote_list(self, ip, subpath="", parent_item=None):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(10); s.connect((ip, 55555)); s.sendall(f"LIST {subpath}".encode())
                data = b""
                while True:
                    chunk = s.recv(1024 * 64)
                    if not chunk: break
                    data += chunk
                if data: self.comm.remote_list_received.emit(json.loads(data.decode()), ip, parent_item)
        except: self.status_lbl.setText(f"Connection to {ip} failed.")

    def populate_remote_view(self, file_list, ip, parent_item):
        if parent_item is None:
            self.file_tree.clear()
            parent_item = QTreeWidgetItem(self.file_tree, [f"{self.current_remote_name} Shared", "--", "Folder", "--", self.current_remote_name])
            parent_item.setIcon(0, self.style().standardIcon(self.style().StandardPixmap.SP_DirIcon)); parent_item.setExpanded(True)
        
        for f in file_list:
            if f['name'].lower() in IGNORE_LIST: continue
            t_item = QTreeWidgetItem(parent_item, [f['name'], f['size'], f['type'], f['date'], self.current_remote_name])
            t_item.setData(0, Qt.ItemDataRole.UserRole, f"REMOTE:{f['rel_path']}")
            t_item.setIcon(0, self.style().standardIcon(self.style().StandardPixmap.SP_DirIcon if f['type'] == 'Folder' else self.style().standardIcon(self.style().StandardPixmap.SP_FileIcon)))
            if f['type'] == 'Folder': t_item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)

    def start_download(self):
        item = self.file_tree.currentItem()
        if not item or not self.current_remote_ip or self.is_downloading: return
        rel_path = str(item.data(0, Qt.ItemDataRole.UserRole)).replace("REMOTE:", "")
        is_folder = item.text(2) == "Folder"
        save_path = QFileDialog.getExistingDirectory(self, "Select Save Location") if is_folder else QFileDialog.getSaveFileName(self, "Save File", item.text(0))[0]
        
        if is_folder and save_path: save_path = os.path.join(save_path, item.text(0))
        if save_path:
            self.is_downloading = True
            self.comm.transfer_status_changed.emit(self.current_remote_ip, "◀", True, item.text(0))
            self.dl_dialog = QProgressDialog(f"Downloading {item.text(0)}...", "Cancel", 0, 100, self)
            self.dl_dialog.setWindowModality(Qt.WindowModality.WindowModal); self.dl_dialog.show()
            threading.Thread(target=self.download_worker, args=(self.current_remote_ip, rel_path, save_path, is_folder, item.text(0)), daemon=True).start()

    def update_dl_dialog(self, val):
        if hasattr(self, 'dl_dialog'): self.dl_dialog.setValue(val)

    def finalize_dl(self, filename, status):
        self.is_downloading = False
        self.comm.transfer_status_changed.emit(self.current_remote_ip, "◀", False, filename)
        if hasattr(self, 'dl_dialog'): self.dl_dialog.close()
        self.status_lbl.setText(status)

    def download_worker(self, ip, rel_path, save_path, is_folder, display_name):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(None); s.connect((ip, 55555)); s.sendall(f"GET {rel_path}".encode())
                header = s.recv(1024).decode().strip()
                if not header: raise Exception("No response")
                total_size = int(header); received_total = 0
                while received_total < total_size:
                    if self.dl_dialog.wasCanceled(): raise Exception("Canceled")
                    meta_raw = s.recv(1024).decode().strip()
                    if not meta_raw: break
                    meta = json.loads(meta_raw); f_rel_path, f_size = meta['path'], meta['size']
                    f_full_path = os.path.join(save_path, f_rel_path) if is_folder else save_path
                    os.makedirs(os.path.dirname(f_full_path), exist_ok=True)
                    with open(f_full_path, 'wb') as f:
                        f_received = 0
                        while f_received < f_size:
                            chunk = s.recv(min(1024 * 1024, f_size - f_received))
                            if not chunk: break
                            f.write(chunk); f_received += len(chunk); received_total += len(chunk)
                            self.comm.download_progress.emit(int((received_total / total_size) * 100))
                self.comm.download_finished.emit(display_name, f"Finished: {display_name}")
        except Exception as e: self.comm.download_finished.emit(display_name, f"Error: {str(e)}")

    def start_server(self):
        def server_thread():
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(('0.0.0.0', 55555)); s.listen(10)
            while True:
                conn, addr = s.accept()
                try:
                    req = conn.recv(1024).decode()
                    if req.startswith("LIST") and self.shared_folder_path:
                        parts = req.split(" ", 1); sub = parts[1] if len(parts) > 1 else ""
                        full_req_path = os.path.join(self.shared_folder_path, sub); files = []
                        if os.path.exists(full_req_path):
                            for i in os.listdir(full_req_path):
                                if i.lower() in IGNORE_LIST: continue
                                p = os.path.join(full_req_path, i); is_dir = os.path.isdir(p)
                                sz = get_folder_size(p) if is_dir else os.path.getsize(p)
                                files.append({"name": i, "rel_path": os.path.relpath(p, self.shared_folder_path), "size": format_size(sz), "type": "Folder" if is_dir else "File", "date": datetime.fromtimestamp(os.path.getmtime(p)).strftime('%Y-%m-%d %H:%M')})
                        conn.sendall(json.dumps(files).encode())
                    elif req.startswith("GET ") and self.shared_folder_path:
                        rel_p = req[4:]; full_p = os.path.join(self.shared_folder_path, rel_p)
                        if os.path.exists(full_p):
                            d_name = os.path.basename(full_p); self.comm.transfer_status_changed.emit(addr[0], "▶", True, d_name)
                            total_to_send = get_folder_size(full_p) if os.path.isdir(full_p) else os.path.getsize(full_p)
                            conn.sendall(str(total_to_send).encode().ljust(1024))
                            to_send = []
                            if os.path.isdir(full_p):
                                for root, dirs, files in os.walk(full_p):
                                    for file in files:
                                        if file.lower() in IGNORE_LIST: continue
                                        fp = os.path.join(root, file); to_send.append((fp, os.path.relpath(fp, full_p)))
                            else: to_send.append((full_p, os.path.basename(full_p)))
                            for f_path, f_rel in to_send:
                                fs = os.path.getsize(f_path); conn.sendall(json.dumps({"path": f_rel, "size": fs}).encode().ljust(1024))
                                with open(f_path, 'rb') as f:
                                    while chunk := f.read(1024 * 1024): conn.sendall(chunk)
                            self.comm.transfer_status_changed.emit(addr[0], "▶", False, d_name)
                except: pass
                finally: conn.close()
        threading.Thread(target=server_thread, daemon=True).start()

    def show_file_context_menu(self, pos):
        menu = QMenu(); dl = menu.addAction("Download"); menu.addSeparator(); cp = menu.addAction("Copy")
        if menu.exec(QCursor.pos()) == dl: self.start_download()

    def add_manual_ip(self):
        ip, nick = self.ip_input.text().strip(), self.nick_input.text().strip() or "Device"
        if ip: self.add_peer_to_ui(ip, nick, True); self.ip_input.clear(); self.nick_input.clear()

    def add_peer_to_ui(self, ip, name, is_manual=False):
        if ip not in self.peers:
            parent = self.root_manual if is_manual else self.root_net
            item = QTreeWidgetItem(parent, [f"{name} ({ip})"]); item.setData(0, Qt.ItemDataRole.UserRole, ip); self.peers[ip] = item

    def init_mdns(self):
        try:
            self.zc = Zeroconf(); ip = self.get_local_ip(); info = ServiceInfo("_ftastic._tcp.local.", f"{socket.gethostname()}._ftastic._tcp.local.", addresses=[socket.inet_aton(ip)], port=55555)
            self.zc.register_service(info); self.browser = ServiceBrowser(self.zc, "_ftastic._tcp.local.", MyListener(self.comm.peer_discovered))
        except: pass

if __name__ == "__main__":
    app = QApplication(sys.argv); window = FTasticApp(); window.show(); sys.exit(app.exec())