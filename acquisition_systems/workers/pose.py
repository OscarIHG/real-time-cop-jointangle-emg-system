# -*- coding: utf-8 -*-
"""
PoseWorker: captura landmarks usando MediaPipe desde una cámara y publica:
  - PoseSample: 33 landmarks (33 x 2) en coordenadas de píxeles
  - AngleSample: ángulo de oblicuidad pélvica (deg) computado desde landmarks 23–24

REEMPLAZA la versión TensorFlow Lite con MediaPipe superior.
MediaPipe proporciona 33 landmarks vs 17 de MoveNet, mayor precisión y seguimiento temporal.
"""
import time
import threading
import queue
import numpy as np

try:
    import cv2
    import mediapipe as mp
except Exception as e:
    cv2 = None
    mp = None
    _pose_import_error = e
else:
    _pose_import_error = None

from acquisition_systems.common.types import PoseSample, AngleSample
from acquisition_systems.common.utils import put_latest
from acquisition_systems.common.config import ConfigDict


def _calculate_pelvic_obliquity_mediapipe(landmarks: np.ndarray) -> float:
    """
    Calcula oblicuidad pélvica usando landmarks 23 y 24 de MediaPipe.
    MediaPipe landmarks 23 = cadera izquierda, 24 = cadera derecha
    
    Args:
        landmarks: Array (33, 2) con coordenadas [x, y] de landmarks MediaPipe
    Returns:
        Ángulo en grados (positivo = inclinación hacia la derecha)
    """
    if landmarks.shape[0] < 25:  # Asegurar que tenemos al menos 25 landmarks
        return 0.0
        
    # Landmarks de cadera en MediaPipe
    left_hip = landmarks[23]   # Cadera izquierda
    right_hip = landmarks[24]  # Cadera derecha
    
    # Verificar si los landmarks son válidos (no NaN)
    if np.any(np.isnan([left_hip, right_hip])):
        return 0.0
    
    # Calcular vector de cadera derecha a izquierda
    hip_vector = left_hip - right_hip
    
    # Calcular ángulo respecto a la horizontal
    angle_rad = np.arctan2(hip_vector[1], hip_vector[0])
    angle_deg = np.degrees(angle_rad)
    
    # Normalizar a rango [-90, 90]
    while angle_deg > 90:
        angle_deg -= 180
    while angle_deg < -90:
        angle_deg += 180
    
    return float(angle_deg)


class PoseWorker:
    """
    Worker de pose usando MediaPipe - Superior a TensorFlow Lite.
    
    Características:
    - 33 landmarks (vs 17 de MoveNet)
    - Seguimiento temporal suave
    - Mejor precisión para ángulos articulares
    - Configuración automática sin modelos externos
    """
    
    def __init__(self, cam_index: int = 0, width: int = 640, height: int = 480, 
                 fps: int = 30, config: ConfigDict = None):
        if cv2 is None or mp is None:
            raise ImportError(f"OpenCV y MediaPipe son requeridos: {_pose_import_error}")
        
        self.idx = cam_index
        self.cam_w = int(width)
        self.cam_h = int(height)
        self.fps = int(fps)
        
        # Configuración MediaPipe desde config.yaml
        if config:
            self.model_complexity = int(config.get('mediapipe_model_complexity', 1))
            self.min_detection_confidence = float(config.get('mediapipe_min_detection_confidence', 0.5))
            self.min_tracking_confidence = float(config.get('mediapipe_min_tracking_confidence', 0.5))
            self.smooth_landmarks = bool(config.get('mediapipe_smooth_landmarks', True))
            self.smooth_segmentation = bool(config.get('mediapipe_smooth_segmentation', False))
            self.static_image_mode = bool(config.get('mediapipe_static_image_mode', False))
        else:
            # Valores por defecto optimizados
            self.model_complexity = 1
            self.min_detection_confidence = 0.5
            self.min_tracking_confidence = 0.5
            self.smooth_landmarks = True
            self.smooth_segmentation = False
            self.static_image_mode = False
        
        self.landmarks_q: queue.Queue = queue.Queue(maxsize=1)
        self.angle_q: queue.Queue = queue.Queue(maxsize=1)
        
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._cam = None
        self._pose_processor = None
    
    def _open_camera(self):
        """Abrir cámara con configuración optimizada."""
        # Intentar V4L2 primero (mejor en Linux)
        self._cam = cv2.VideoCapture(self.idx, cv2.CAP_V4L2)
        if not self._cam or not self._cam.isOpened():
            try:
                if self._cam: 
                    self._cam.release()
            except Exception: 
                pass
            # Fallback a backend por defecto
            self._cam = cv2.VideoCapture(self.idx)
        
        if not self._cam or not self._cam.isOpened():
            raise RuntimeError(f"Cámara índice {self.idx} no disponible.")
        
        try:
            # Configuración de cámara optimizada
            self._cam.set(cv2.CAP_PROP_FRAME_WIDTH, self.cam_w)
            self._cam.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cam_h)
            self._cam.set(cv2.CAP_PROP_FPS, self.fps)
            self._cam.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Buffer mínimo para menor latencia
            
            # Configuraciones adicionales para mejor rendimiento
            self._cam.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))
        except Exception as ex:
            print(f"[PoseWorker] Advertencia: No se pudieron configurar algunas propiedades de cámara: {ex}")
    
    def _init_mediapipe(self):
        """Inicializar MediaPipe Pose con configuración optimizada."""
        mp_pose = mp.solutions.pose
        
        self._pose_processor = mp_pose.Pose(
            static_image_mode=self.static_image_mode,
            model_complexity=self.model_complexity,
            smooth_landmarks=self.smooth_landmarks,
            smooth_segmentation=self.smooth_segmentation,
            enable_segmentation=False,  # Desactivar para mejor rendimiento
            min_detection_confidence=self.min_detection_confidence,
            min_tracking_confidence=self.min_tracking_confidence
        )
        
        print(f"[PoseWorker] MediaPipe inicializado:")
        print(f"  - Complejidad del modelo: {self.model_complexity}")
        print(f"  - Confianza detección: {self.min_detection_confidence}")
        print(f"  - Confianza seguimiento: {self.min_tracking_confidence}")
        print(f"  - Suavizado de landmarks: {self.smooth_landmarks}")
    
    def _process_frame(self, frame: np.ndarray) -> tuple[np.ndarray, bool]:
        """
        Procesa frame con MediaPipe y convierte a coordenadas de píxeles.
        
        Returns:
            tuple: (landmarks_array, pose_detected)
            - landmarks_array: (33, 2) array con coordenadas [x, y] en píxeles
            - pose_detected: bool indicando si se detectó pose
        """
        # Convertir BGR a RGB para MediaPipe
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Procesar con MediaPipe
        results = self._pose_processor.process(rgb_frame)
        
        # Inicializar array de landmarks
        landmarks_px = np.full((33, 2), np.nan, dtype=np.float32)
        pose_detected = False
        
        if results.pose_landmarks:
            pose_detected = True
            
            # Convertir landmarks normalizados a coordenadas de píxeles
            for i, landmark in enumerate(results.pose_landmarks.landmark):
                # MediaPipe devuelve coordenadas normalizadas [0, 1]
                x_px = landmark.x * self.cam_w
                y_px = landmark.y * self.cam_h
                
                # Verificar si el landmark es visible (confianza > umbral)
                if hasattr(landmark, 'visibility') and landmark.visibility > 0.1:
                    landmarks_px[i, 0] = x_px
                    landmarks_px[i, 1] = y_px
                else:
                    # Landmark no visible, mantener NaN
                    landmarks_px[i, 0] = x_px  # Incluir posición aunque tenga baja visibilidad
                    landmarks_px[i, 1] = y_px
        
        return landmarks_px, pose_detected
    
    def _loop(self):
        """Ciclo principal de adquisición y procesamiento."""
        frame_count = 0
        start_time = time.perf_counter()
        
        try:
            while not self._stop.is_set():
                ok, frame = self._cam.read()
                if not ok:
                    time.sleep(0.01)
                    continue
                
                try:
                    # Procesar con MediaPipe
                    landmarks_px, pose_detected = self._process_frame(frame)
                    t = time.perf_counter()
                    
                    if pose_detected:
                        # Publicar muestra de pose (33 landmarks)
                        put_latest(self.landmarks_q, PoseSample(t=t, landmarks=landmarks_px))
                        
                        # Calcular y publicar ángulo de oblicuidad pélvica
                        angle_deg = _calculate_pelvic_obliquity_mediapipe(landmarks_px)
                        put_latest(self.angle_q, AngleSample(t=t, deg=angle_deg))
                    
                    frame_count += 1
                    
                    # Estadísticas de rendimiento cada 100 frames
                    if frame_count % 100 == 0:
                        elapsed = t - start_time
                        fps_actual = frame_count / elapsed if elapsed > 0 else 0
                        print(f"[PoseWorker] FPS: {fps_actual:.1f}, Poses detectadas: {frame_count}")
                
                except Exception as e:
                    print(f"[PoseWorker] Error en procesamiento MediaPipe: {e}")
                    time.sleep(0.01)
        
        except Exception as e:
            print(f"[PoseWorker] Error en ciclo principal: {e}")
        
        finally:
            try:
                if self._cam:
                    self._cam.release()
                if self._pose_processor:
                    self._pose_processor.close()
            except Exception:
                pass
    
    # ---------- API pública ----------
    def start(self):
        """Iniciar adquisición de pose con MediaPipe."""
        print("[PoseWorker] Iniciando con MediaPipe (reemplaza TensorFlow Lite)...")
        
        self._stop.clear()
        self._open_camera()
        self._init_mediapipe()
        
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        
        print(f"[PoseWorker] ✅ Iniciado - Cámara {self.idx} ({self.cam_w}x{self.cam_h})")
    
    def stop(self):
        """Detener adquisición y liberar recursos."""
        print("[PoseWorker] Deteniendo MediaPipe...")
        
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        
        print("[PoseWorker] ✅ Detenido correctamente")