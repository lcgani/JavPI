import queue
import asyncio
import logging
import threading

import numpy as np
import sounddevice as sd

from typing import Optional

logger = logging.getLogger(__name__)

class AudioCaptureError(Exception):
    pass

class AudioCapture:
    def __init__(
        self,
        sample_rate=16000,
        channels=1,
        dtype='int16',
        blocksize=512,
        device=None
    ):
        self.dtype = dtype
        self.device = device
        self.channels = channels
        self.blocksize = blocksize
        self.sample_rate = sample_rate
        
        self.stream = None
        self.is_recording = False

        self._lock = threading.Lock()
        self.audio_queue = queue.Queue(maxsize=100)

    def start_recording(self):
        with self._lock:
            if self.is_recording:
                return
            
            try:
                self.stream = sd.InputStream(
                    samplerate=self.sample_rate,
                    channels=self.channels,
                    dtype=self.dtype,
                    blocksize=self.blocksize,
                    device=self.device,
                    callback=self._audio_callback
                )
                
                self.stream.start()
                self.is_recording = True
            
            except Exception as e:
                raise AudioCaptureError(f"Failed to start recording: {e}") from e

    def stop_recording(self):
        with self._lock:
            if not self.is_recording:
                return
            
            try:
                if self.stream:
                    self.stream.stop()
                    self.stream.close()
                    self.stream = None
                
                self.is_recording = False
                self.clear_queue()
            
            except Exception as e:
                pass

    def _audio_callback(self, indata, frames, time_info, status):
        try:
            audio_bytes = indata.tobytes()
            
            try:
                self.audio_queue.put_nowait(audio_bytes)
            except queue.Full:
                pass
        
        except Exception:
            pass

    def get_audio_chunk(self, timeout=0.1):
        try:
            return self.audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    async def get_audio_chunk_async(self, timeout=0.1):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.get_audio_chunk, timeout)

    def clear_queue(self):
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break
