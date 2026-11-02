"""
Live video AI detection: bounded ring buffer, micro-batching and model-version swap (PoC)
Demonstrates, in pure Python with simulated frames (no camera, model, database or Redis):
  1. Per-camera ring buffer (deque(maxlen=2)) that drops stale frames instead of queueing them
  2. Micro-batch collection across cameras (up to 8 frames per batch)
  3. Thread-safe swap/rollback of the active model version (a version string; no model loading)
A real pipeline would add the camera reader threads, the inference call and a database writer.
"""
import time
import threading
from collections import deque
from typing import List


class FramePacket:
    def __init__(self, camera_id: str, frame_seq: int, captured_at: float, payload_shape: tuple = (720, 1280, 3)):
        self.camera_id = camera_id
        self.frame_seq = frame_seq
        self.captured_at = captured_at
        self.payload_shape = payload_shape


class BoundedCameraIngestor:
    """Prevents frame backup by keeping only the freshest N frames per stream."""
    def __init__(self, camera_id: str, maxlen: int = 2):
        self.camera_id = camera_id
        self.ring_buffer = deque(maxlen=maxlen)
        self.dropped_frames = 0
        self.lock = threading.Lock()

    def push_frame(self, packet: FramePacket):
        with self.lock:
            if len(self.ring_buffer) == self.ring_buffer.maxlen:
                self.dropped_frames += 1
            self.ring_buffer.append(packet)

    def pop_latest(self):
        with self.lock:
            return self.ring_buffer.pop() if self.ring_buffer else None


class AtomicModelRegistry:
    """Thread-safe swap and rollback of the active model version name."""
    def __init__(self, initial_version: str = "v1_yolov8_onnx"):
        self._active_version = initial_version
        self._previous_version = initial_version
        self._lock = threading.RLock()

    def hot_swap(self, new_version: str):
        with self._lock:
            self._previous_version = self._active_version
            self._active_version = new_version

    def rollback(self):
        with self._lock:
            self._active_version = self._previous_version

    def get_active_version(self) -> str:
        with self._lock:
            return self._active_version


def collect_micro_batch(ingestors: List[BoundedCameraIngestor], max_batch: int = 8) -> List[FramePacket]:
    batch = []
    for ing in ingestors:
        pkt = ing.pop_latest()
        if pkt is not None:
            batch.append(pkt)
            if len(batch) >= max_batch:
                break
    return batch


if __name__ == "__main__":
    cam1 = BoundedCameraIngestor("cam_site_a_01", maxlen=2)
    registry = AtomicModelRegistry("v1_onnx_fp16")
    for seq in range(1, 6):
        cam1.push_frame(FramePacket("cam_site_a_01", seq, time.time()))
    batch = collect_micro_batch([cam1])
    print(f"Active Model: {registry.get_active_version()} | Freshest seq={batch[0].frame_seq} | Dropped stale={cam1.dropped_frames}")
