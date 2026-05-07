import sys
import os
import re
import subprocess
import shutil
from PyQt5 import QtWidgets
from PyQt5.QtCore import QRegExp, QObject, pyqtSignal, QThread
from PyQt5.QtGui import QIcon, QRegExpValidator, QDragEnterEvent, QDropEvent
from GUI import Ui_Window
import ffmpeg
import datetime


def get_bundle_resource(name):
    if hasattr(sys, '_MEIPASS'):
        bundled_path = os.path.join(sys._MEIPASS, name)
        if os.path.isfile(bundled_path):
            return bundled_path
    if os.path.isfile(name):
        return os.path.abspath(name)
    return None


def find_ffmpeg_executable():
    ffmpeg_path = shutil.which('ffmpeg')
    if ffmpeg_path:
        return ffmpeg_path

    binary_name = 'ffmpeg.exe' if os.name == 'nt' else 'ffmpeg'
    return get_bundle_resource(binary_name)


# Класс для многопоточности
class FFmpegWorker(QObject):
    progress = pyqtSignal(int)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, cmd, total_duration=None, total_frames=None):
        super().__init__()
        self.cmd = cmd
        self.total_duration = total_duration
        self.total_frames = total_frames

    def run(self):
        try:
            self.progress.emit(0)
            process = subprocess.Popen(
                self.cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )
            
            duration_ms = int(self.total_duration * 1000) if self.total_duration else None
            ffmpeg_output = []
            for line in process.stdout:
                line = line.strip()
                if line:
                    ffmpeg_output.append(line)
                if self.total_frames and self.total_frames > 0 and 'frame=' in line:
                    frame_match = re.search(r'frame=\s*(\d+)', line)
                    if frame_match:
                        current_frame = int(frame_match.group(1))
                        percent = min(int((current_frame / self.total_frames) * 100), 100)
                        self.progress.emit(percent)
                elif duration_ms and 'time=' in line:
                    time_match = re.search(r'time=(\d+):(\d+):(\d+\.\d+)', line)
                    if time_match:
                        hours, minutes, seconds = map(float, time_match.groups())
                        current_time_ms = (hours * 3600 + minutes * 60 + seconds) * 1000
                        percent = min(int((current_time_ms / duration_ms) * 100), 100)
                        self.progress.emit(percent)
                elif line.startswith('progress=') and line.split('=', 1)[1] == 'end':
                    self.progress.emit(100)
            process.wait()
            if process.returncode == 0:
                self.progress.emit(100)
                self.finished.emit()
            else:
                error_text = '\n'.join(ffmpeg_output[-40:]) if ffmpeg_output else 'Нет вывода FFmpeg.'
                self.error.emit(f'FFmpeg вернул: {process.returncode}\n\n{error_text}')
        except Exception as exc:
            self.error.emit(str(exc))

# Основное окно
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super(MainWindow, self).__init__()
        self.ui = Ui_Window()
        self.ui.setupUi(self)
        icon_path = get_bundle_resource('icon.ico')
        if icon_path:
            self.setWindowIcon(QIcon(icon_path))
        self.setFixedSize(self.size())
        self.setAcceptDrops(True)

        filename_mask = QRegExpValidator(QRegExp("[^/\\\\:*?\"<>|]*"))
        self.ui.fileName.setValidator(filename_mask)

        # Поиск всех отключенных виджетов
        self._user_param_widgets = [
            widget for widget in self.findChildren(QtWidgets.QWidget)
            if not widget.isEnabled()
            and widget not in (self.ui.compressB, self.ui.resolution)
        ]


        self.ui.resChange.toggled.connect(self.ui.resolution.setEnabled)
        self.ui.researchB.clicked.connect(self.researchB_clicked)
        self.ui.userParamether.toggled.connect(self.userParamether_toggled)
        self.ui.filePath.textChanged.connect(self.check_compressB_enabled)
        self.ui.compressB.clicked.connect(self.compress)
        self.check_compressB_enabled()

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            file_path = urls[0].toLocalFile()
            if os.path.isfile(file_path):
                self.ui.filePath.setText(file_path)

    # Кнопка Обзор
    def researchB_clicked(self):
        file_name, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Выберите файл",
            "c:\\",
            "Видео (*.mp4 *.avi *.mkv *.webm *.mov);;Все файлы (*)"
        )
        if file_name:
            self.ui.filePath.setText(file_name)

    # Флажок Параметры
    def userParamether_toggled(self, checked):
        for widget in self._user_param_widgets:
            widget.setEnabled(checked)

    def check_compressB_enabled(self):
        path = self.ui.filePath.text()
        self.ui.compressB.setEnabled(bool(path) and os.path.isfile(path))

    # Вся магия
    def compress(self):
        path = self.ui.filePath.text().strip()
        if not path:
            QtWidgets.QMessageBox.warning(self, "Предупреждение", "Файл не выбран")
            return
        if not os.path.exists(path):
            QtWidgets.QMessageBox.critical(self, "Ошибка!", f"Ошибка: файл не найден - {path}")
            return
        
        directory = os.path.dirname(path)
        filename = os.path.basename(path)
        name_without_ext, _ = os.path.splitext(filename)
        
        # Название файла
        if self.ui.fileName.text().strip():
            output_name = self.ui.fileName.text().strip()
        else:
            output_name = f"{name_without_ext}_compressed"
        ext = self.ui.fileExtens.currentText()
        output_path = os.path.join(directory, f"{output_name}{ext}")

            
        # Сжатие
        try:
            if self.ui.userParamether.isChecked():
                bitrate_text = self.ui.vbitrate.currentText()
                abitrate_text = self.ui.abitrate.currentText()
                bitrate = f"{''.join(ch for ch in bitrate_text if ch.isdigit())}k"
                abitrate = f"{''.join(ch for ch in abitrate_text if ch.isdigit())}k"
                framerate = self.ui.framerate.currentText()
                if self.ui.graphUse.isChecked():
                    preset_mapping = {
                        "Очень быстро": "p1",
                        "Быстрее": "p2",
                        "Быстро": "p3",
                        "Средне": "p4",
                        "Медленно": "p5",
                        "Медленнее": "p6",
                        "Очень медленно": "p7"
                    }
                    preset = preset_mapping.get(self.ui.speed.currentText(), "p7")
                    videocodec = 'h264_nvenc'
                else:
                    preset_mapping = {
                    "Очень быстро": "veryfast",
                    "Быстрее": "faster",
                    "Быстро": "fast",
                    "Средне": "medium",
                    "Медленно": "slow",
                    "Медленнее": "slower",
                    "Очень медленно": "veryslow"
                }
                    preset = preset_mapping.get(self.ui.speed.currentText(), "veryslow")
                    videocodec = 'libx264'


            else:
                bitrate = "3000k"
                abitrate = "128k"
                framerate = "30"
                videocodec = 'libx264'
                preset = "veryslow"
                self.ui.resChange.setChecked(False)


            if self.ui.resChange.isChecked():
                resolution_text = self.ui.resolution.currentText()
                resolution_value = resolution_text.split()[-1]
                if "x" in resolution_value:
                    width, height = resolution_value.split("x")
                    resolution = f"{width}:{height}"
                else:
                    resolution = resolution_value
                filter_arg = f'scale={resolution}, fps={framerate}'
            else:
                filter_arg = f'fps={framerate}'

            ffmpeg_path = find_ffmpeg_executable()
            if not ffmpeg_path:
                QtWidgets.QMessageBox.critical(
                    self,
                    "Ошибка!",
                    "FFmpeg не найден. Установите ffmpeg и добавьте его в PATH, или соберите exe вместе с ffmpeg.exe."
                )
                return

            ffmpeg_args = [
                ffmpeg_path,
                '-y',
                '-i', path,
                '-vcodec', videocodec,
                '-pix_fmt', 'yuv420p',
                '-preset', preset,
                '-b:v', bitrate,
                '-acodec', 'aac',
                '-b:a', abitrate,
                '-vf', filter_arg,
                '-progress', 'pipe:1',
                '-nostats',
                output_path
            ]

            self.ui.progressBar.setValue(0)
            self.ui.compressB.setEnabled(False)

            # Основа прогрессбара
            duration = 0.0
            total_frames = 0
            try:
                probe = ffmpeg.probe(path)
                duration = float(probe['format'].get('duration', 0.0))
                video_stream = next(s for s in probe['streams'] if s['codec_type'] == 'video')
                total_frames = int(video_stream.get('nb_frames', 0))
                if total_frames == 0 and duration > 0:
                    fps = eval(video_stream['r_frame_rate'])
                    total_frames = int(duration * fps)
            except Exception:
                duration = 0.0
                total_frames = 0

            # Запуск FFmpeg
            self.worker = FFmpegWorker(ffmpeg_args, duration, total_frames)
            self.worker_thread = QThread()
            self.worker.moveToThread(self.worker_thread)
            self.worker.progress.connect(self.ui.progressBar.setValue)
            self.worker.finished.connect(lambda: self._on_compress_finished(output_path))
            self.worker.error.connect(self._on_compress_error)
            self.worker_thread.started.connect(self.worker.run)
            self.worker_thread.start()
        except Exception as e:
            self.ui.compressB.setEnabled(bool(self.ui.filePath.text() and os.path.isfile(self.ui.filePath.text())))
            QtWidgets.QMessageBox.critical(self, "Ошибка!", str(e))

    def _on_compress_finished(self, output_path):
        self.ui.compressB.setEnabled(bool(self.ui.filePath.text() and os.path.isfile(self.ui.filePath.text())))
        self.worker_thread.quit()
        self.worker_thread.wait()
        self.ui.progressBar.setValue(100)
        QtWidgets.QMessageBox.information(self, "Успех", f"Видео успешно сжато и сохранено как {output_path}")

    def _on_compress_error(self, error_msg):
        self.ui.compressB.setEnabled(bool(self.ui.filePath.text() and os.path.isfile(self.ui.filePath.text())))
        self.ui.progressBar.setValue(0)
        self.worker_thread.quit()
        self.worker_thread.wait()
        log_name = f"ffmpeg_error_{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"
        with open(log_name, "w", encoding="utf-8") as log_file:
            log_file.write(error_msg)
        QtWidgets.QMessageBox.critical(self, "Ошибка!", f"Произошла ошибка при сжатии видео!\n\nСодержание ошибки сохранено в файл: {log_name}")

# Наконец, запуск
def main():
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
