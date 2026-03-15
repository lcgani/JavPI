import queue
import threading
import numpy as np
import sounddevice as sd

from collections import deque


class AudioPlaybackError(Exception):
    pass


class AudioPlayback:

    def __init__(
        self,
        sample_rate=24000,
        channels=1,
        dtype='float32',
        blocksize=2400,
        device=None
    ):
        self.dtype = dtype
        self.device = device
        self.channels = channels
        self.blocksize = blocksize
        self.sample_rate = sample_rate

        self.stream = None
        self.is_playing = False
        self._is_speaking = False
        self._lock = threading.Lock()
        self.audio_queue = queue.Queue(maxsize=200)

        self._chunks = deque()
        self._pos = 0

        # Recent rendered speaker audio for echo-suppression checks.
        self._recent_seconds = 2.0
        self._recent_len = max(1, int(self.sample_rate * self._recent_seconds))
        self._recent_audio = np.zeros(self._recent_len, dtype=np.float32)
        self._recent_index = 0
        self._recent_lock = threading.Lock()

    @property
    def is_speaking(self):
        return self._is_speaking

    def start_playback(self):
        with self._lock:
            if self.is_playing:
                return

            try:
                self.stream = sd.OutputStream(
                    samplerate=self.sample_rate,
                    channels=self.channels,
                    dtype=self.dtype,
                    blocksize=self.blocksize,
                    device=self.device,
                    callback=self._audio_callback
                )
                self.stream.start()
                self.is_playing = True
            except Exception as e:
                raise AudioPlaybackError(f"Failed to start playback: {e}") from e

    def stop_playback(self):
        with self._lock:
            if not self.is_playing:
                return
            try:
                if self.stream:
                    self.stream.stop()
                    self.stream.close()
                    self.stream = None
                self.is_playing = False
                self._chunks.clear()
                self._pos = 0
                self._is_speaking = False
                with self._recent_lock:
                    self._recent_audio.fill(0.0)
                    self._recent_index = 0
            except Exception:
                pass

    def _audio_callback(self, outdata, frames, time_info, status):
        try:
            while True:
                try:
                    chunk = self.audio_queue.get_nowait()
                    if chunk is None:
                        self._chunks.clear()
                        self._pos = 0
                        self._is_speaking = False
                        outdata.fill(0)
                        self._store_recent(outdata[:, 0])
                        return

                    self._chunks.append(chunk)
                except queue.Empty:
                    break

            filled = 0

            while filled < frames and self._chunks:
                front = self._chunks[0]
                available = len(front) - self._pos
                need = frames - filled

                if available <= need:
                    outdata[filled:filled + available, 0] = front[self._pos:]
                    filled += available
                    self._chunks.popleft()
                    self._pos = 0
                else:
                    outdata[filled:, 0] = front[self._pos:self._pos + need]
                    self._pos += need
                    filled = frames

            if filled < frames:
                outdata[filled:] = 0
                self._is_speaking = filled > 0
            else:
                self._is_speaking = True

            self._store_recent(outdata[:, 0])

        except Exception:
            outdata.fill(0)
            self._store_recent(outdata[:, 0])

    def queue_audio(self, audio_array):
        try:
            if self.audio_queue.qsize() > 400:
                try:
                    self.audio_queue.get_nowait()
                except queue.Empty:
                    pass
            self.audio_queue.put_nowait(audio_array)
        except queue.Full:
            pass

    def clear_queue(self):
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break
        self._chunks.clear()
        self._pos = 0
        self._is_speaking = False
        with self._recent_lock:
            self._recent_audio.fill(0.0)
            self._recent_index = 0

    def flush_signal(self):
        try:
            self.audio_queue.put_nowait(None)
        except queue.Full:
            pass

    def _store_recent(self, mono_chunk):
        chunk = np.asarray(mono_chunk, dtype=np.float32).reshape(-1)
        if chunk.size == 0:
            return

        if chunk.size >= self._recent_len:
            with self._recent_lock:
                self._recent_audio[:] = chunk[-self._recent_len:]
                self._recent_index = 0
            return

        with self._recent_lock:
            end = self._recent_index + chunk.size
            if end <= self._recent_len:
                self._recent_audio[self._recent_index:end] = chunk
            else:
                first = self._recent_len - self._recent_index
                self._recent_audio[self._recent_index:] = chunk[:first]
                self._recent_audio[:chunk.size - first] = chunk[first:]
            self._recent_index = (self._recent_index + chunk.size) % self._recent_len

    def get_recent_audio(self, seconds=0.6):
        wanted = max(1, min(int(float(seconds) * self.sample_rate), self._recent_len))
        with self._recent_lock:
            idx = self._recent_index
            start = (idx - wanted) % self._recent_len
            if start < idx:
                return self._recent_audio[start:idx].copy()
            return np.concatenate((self._recent_audio[start:], self._recent_audio[:idx])).copy()
