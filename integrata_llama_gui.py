
import sys
import requests
import subprocess
import threading
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton, QListWidget, QListWidgetItem, QSplitter, QLineEdit, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer

API_URL = "http://127.0.0.1:8000/reason"
SERVER_CMD = [sys.executable, "-m", "uvicorn", "integrata_llama_api:app", "--reload"]

class IntegrataLlamaGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("IntegrataLlama Dashboard & Reasoning GUI")
        self.resize(1000, 700)
        self.layout = QVBoxLayout(self)

        # Dashboard controls
        dash_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start Server", self)
        self.start_btn.clicked.connect(self.start_server)
        self.stop_btn = QPushButton("Stop Server", self)
        self.stop_btn.clicked.connect(self.stop_server)
        self.stop_btn.setEnabled(False)
        self.status_label = QLabel("Server status: <b>Stopped</b>")
        dash_layout.addWidget(self.start_btn)
        dash_layout.addWidget(self.stop_btn)
        dash_layout.addWidget(self.status_label)
        dash_layout.addStretch()
        self.layout.addLayout(dash_layout)

        # Input area
        self.input_box = QTextEdit(self)
        self.input_box.setPlaceholderText("Enter your task, question, or command for IntegrataLlama...")
        self.layout.addWidget(QLabel("Input:"))
        self.layout.addWidget(self.input_box)

        # Send button
        self.send_btn = QPushButton("Send to LLaMA", self)
        self.send_btn.clicked.connect(self.send_request)
        self.send_btn.setEnabled(False)
        self.layout.addWidget(self.send_btn)

        # Splitter for output and reasoning
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.layout.addWidget(self.splitter)

        # Output area
        self.output_area = QTextEdit(self)
        self.output_area.setReadOnly(True)
        self.splitter.addWidget(self.output_area)

        # Reasoning steps area
        self.reasoning_list = QListWidget(self)
        self.splitter.addWidget(self.reasoning_list)
        self.splitter.setSizes([600, 300])

        # Status bar
        self.status = QLabel("")
        self.layout.addWidget(self.status)

        # Server process
        self.server_proc = None
        self.check_timer = QTimer()
        self.check_timer.timeout.connect(self.check_server_status)
        self.check_timer.start(2000)

    def start_server(self):
        if self.server_proc is not None:
            QMessageBox.warning(self, "Warning", "Server is already running.")
            return
        self.status.setText("Starting server...")
        def run_server():
            self.server_proc = subprocess.Popen(SERVER_CMD, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        threading.Thread(target=run_server, daemon=True).start()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.send_btn.setEnabled(True)
        self.status_label.setText("Server status: <b>Starting...</b>")

    def stop_server(self):
        if self.server_proc is not None:
            self.server_proc.terminate()
            self.server_proc = None
            self.status.setText("Server stopped.")
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.send_btn.setEnabled(False)
            self.status_label.setText("Server status: <b>Stopped</b>")

    def check_server_status(self):
        try:
            resp = requests.get("http://127.0.0.1:8000/", timeout=1)
            if resp.status_code == 200:
                self.status_label.setText("Server status: <b>Running</b>")
                self.send_btn.setEnabled(True)
                self.stop_btn.setEnabled(True)
                self.start_btn.setEnabled(False)
            else:
                self.status_label.setText("Server status: <b>Stopped</b>")
                self.send_btn.setEnabled(False)
                self.stop_btn.setEnabled(False)
                self.start_btn.setEnabled(True)
        except Exception:
            self.status_label.setText("Server status: <b>Stopped</b>")
            self.send_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.start_btn.setEnabled(True)

    def send_request(self):
        user_input = self.input_box.toPlainText().strip()
        if not user_input:
            self.status.setText("Please enter a prompt.")
            return
        self.status.setText("Processing...")
        self.output_area.clear()
        self.reasoning_list.clear()
        try:
            resp = requests.post(API_URL, json={"input": user_input}, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                self.output_area.setPlainText(str(data.get("result", "No result.")))
                for step in data.get("reasoning_steps", []):
                    QListWidgetItem(step, self.reasoning_list)
                self.status.setText("Done.")
            else:
                self.status.setText(f"Error: {resp.status_code} {resp.text}")
        except Exception as e:
            self.status.setText(f"Request failed: {e}")

def main():
    app = QApplication(sys.argv)
    gui = IntegrataLlamaGUI()
    gui.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
