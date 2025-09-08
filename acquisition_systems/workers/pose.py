# -*- coding: utf-8 -*-
"""
PoseWorker: captura landmarks usando TFLite + MoveNet desde una cámara y publica:
  - PoseSample: 17 landmarks (17 x 2) en coordenadas de píxeles
  - AngleSample: ángulo de oblicuidad pélvica (deg) computado desde landmarks 11–12

Esto reemplaza la dependencia de MediaPipe por tflite-runtime.
"""
import time
import threading
import queue
import os
import numpy as np

try:
    import cv2
    import tflite_runtime.interpreter as tflite
except Exception as e:
    cv2 = None
    tflite = None
    _pose_import_error = e
else:
    _pose_import_error = None

from acquisition_systems.common.types import PoseSample, AngleSample
from acquisition_systems.common.utils import put_latest, pelvic_obliquity_deg_from_landmarks


def _repo_root() -> str:
    here = os.path.abspath(os.path.dirname(__file__))
    # Sube dos niveles (desde /workers/pose.py a /)
    return os.path.abspath(os.path.join(here, os.pardir, os.pardir))


class PoseWorker:
    # MoveNet Lightning espera entrada de 192x192
    INPUT_W = 192
    INPUT_H = 192
    MIN_CONFIDENCE = 0.3  # Umbral de confianza para keypoints

    def __init__(self, cam_index: int = 0, width: int = 640, height: int = 480, fps: int = 30):
        if cv2 is None or tflite is None:
            raise ImportError(f"OpenCV y tflite-runtime son requeridos: {_pose_import_error}")

        self.idx = cam_index
        self.cam_w = int(width)   # Ancho de captura de la cámara
        self.cam_h = int(height)  # Alto de captura de la cámara
        self.fps = int(fps)

        self.landmarks_q: queue.Queue = queue.Queue(maxsize=1)
        self.angle_q: queue.Queue = queue.Queue(maxsize=1)

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._cam = None

        # TFLite
        self._interpreter = None
        self._input_details = None
        self._output_details = None

    def _open_camera(self):
        self._cam = cv2.VideoCapture(self.idx, cv2.CAP_V4L2)
        if not self._cam or not self._cam.isOpened():
            try:
                if self._cam: self._cam.release()
            except Exception: pass
            self._cam = cv2.VideoCapture(self.idx)

        if not self._cam or not self._cam.isOpened():
            raise RuntimeError(f"Cámara índice {self.idx} no disponible.")

        try:
            self._cam.set(cv2.CAP_PROP_FRAME_WIDTH, self.cam_w)
            self._cam.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cam_h)
            self._cam.set(cv2.CAP_PROP_FPS, self.fps)
            self._cam.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

    def _load_model(self):
        """Carga el intérprete TFLite."""
        model_path = os.path.join(_repo_root(), "models", "movenet_lightning.tflite")
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Modelo no encontrado en {model_path}. Asegúrate de descargarlo.")
            
        self._interpreter = tflite.Interpreter(model_path=model_path)
        self._interpreter.allocate_tensors()
        
        self._input_details = self._interpreter.get_input_details()
        self._output_details = self._interpreter.get_output_details()
        
        # MoveNet espera entrada int32 o uint8 (depende del modelo, el nuestro es uint8)
        # O float32. Verificamos el tipo.
        self.input_dtype = self._input_details[0]['dtype']


    def _process_frame(self, frame: np.ndarray) -> np.ndarray:
        """Redimensiona, alimenta el modelo y procesa la salida a coordenadas de píxeles."""
        
        # 1. Preparar imagen: redimensionar a 192x192
        img_resized = cv2.resize(frame, (self.INPUT_W, self.INPUT_H))
        
        # Convertir BGR a RGB
        img_rgb = cv2.cvtColor(img_resized, cv2.COLOR_BGR2RGB)
        
        # Añadir dimensión de batch y castear al tipo de entrada (usualmente uint8 o float32)
        input_data = np.expand_dims(img_rgb, axis=0)
        
        if self.input_dtype == np.float32:
             # Normalizar si el modelo espera float
             input_data = (np.float32(input_data) - 127.5) / 127.5
        else:
            # Asegurarse de que sea uint8 si no es float
             input_data = np.uint8(input_data)


        # 2. Correr inferencia
        self._interpreter.set_tensor(self._input_details[0]['index'], input_data)
        self._interpreter.invoke()

        # 3. Obtener salida (Forma: [1, 1, 17, 3]) 3 = (y, x, conf)
        keypoints_with_scores = self._interpreter.get_tensor(self._output_details[0]['index'])
        keypoints = keypoints_with_scores[0, 0] # Quedarse solo con los 17 puntos

        # 4. Procesar salida: convertir a coordenadas de píxeles (X, Y)
        # La salida de MoveNet está en [y, x, conf] normalizado a [0, 1]
        # Necesitamos convertir a [x_px, y_px] escalado a self.cam_w, self.cam_h
        
        output_landmarks_px = np.zeros((17, 2), dtype=np.float32)

        for i in range(17):
            y_norm, x_norm, confidence = keypoints[i]
            
            if confidence >= self.MIN_CONFIDENCE:
                # Escalar a las dimensiones originales de la cámara
                x_px = x_norm * self.cam_w
                y_px = y_norm * self.cam_h
                output_landmarks_px[i, 0] = x_px
                output_landmarks_px[i, 1] = y_px
            else:
                # Si la confianza es baja, marcar como NaN
                output_landmarks_px[i, 0] = np.nan
                output_landmarks_px[i, 1] = np.nan
        
        return output_landmarks_px # Forma final: (17, 2) con formato [X, Y]

    # ---------- ciclo de adquisición ----------
    def _loop(self):
        try:
            while not self._stop.is_set():
                ok, frame = self._cam.read()
                if not ok:
                    time.sleep(0.01)
                    continue

                # Procesar con TFLite/MoveNet
                try:
                    landmarks_px = self._process_frame(frame) # (17, 2) en formato [x, y]
                    t = time.perf_counter()

                    # Publicar muestra de pose (17 landmarks)
                    put_latest(self.landmarks_q, PoseSample(t=t, landmarks=landmarks_px))

                    # Calcular y publicar ángulo (usando la función de utils actualizada)
                    ang = float(pelvic_obliquity_deg_from_landmarks(landmarks_px))
                    put_latest(self.angle_q, AngleSample(t=t, deg=ang))
                
                except Exception as e:
                    print(f"[PoseWorker Error] Fallo en procesamiento TFLite: {e}")
                    # Dormir brevemente si falla la inferencia
                    time.sleep(0.005)

        finally:
            try:
                if self._cam:
                    self._cam.release()
            except Exception:
                pass

    # ---------- API pública ----------
    def start(self):
        """Abrir cámara, cargar modelo TFLite, e iniciar hilo de captura."""
        self._stop.clear()
        self._open_camera()
        self._load_model() # Cargar el intérprete
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Solicitar parada y unir el hilo; libera recursos."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None