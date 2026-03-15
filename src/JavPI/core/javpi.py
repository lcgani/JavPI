import io
import asyncio
import time
import re
import numpy as np
import torch
import torchaudio

from PIL import Image
from collections import deque
from google.genai import types
from ..gemini.client import GeminiLiveClient
from ..audio.capture import AudioCapture
from ..audio.playback import AudioPlayback
from ..vision.screen import ScreenCapture
from ..tools.registry import get_tools, execute_tool
from ..cloud import CloudReporter


class JavPI:
    def __init__(self, api_key):
        self.gemini = None
        self.api_key = api_key

        self.running = False
        self._session_handle = None
        # Disable resumption to avoid stale context leakage across reconnects.
        self._use_session_resumption = False

        self.mic = AudioCapture(sample_rate=16000, blocksize=512)
        self.speaker = AudioPlayback(sample_rate=24000, blocksize=2400)

        self.screen = ScreenCapture()
        self._tools = get_tools()

        self._screen_send_lock = asyncio.Lock()
        self._screen_interval_sec = 1.0
        self._last_screen_sent_ts = 0.0

        # Interruption gate state.
        self._speech_window_samples = int(0.64 * self.mic.sample_rate)
        self._speech_window = deque()
        self._speech_window_len = 0
        self._noise_floor_db = -56.0
        self._noise_alpha = 0.92
        self._min_rms_db = -52.0
        self._snr_threshold_db = 6.0
        self._speech_band_ratio_threshold = 0.42
        self._speech_trigger_frames = 2
        self._speech_release_frames = 6
        self._speech_hits = 0
        self._speech_misses = 0
        self._interrupting = False
        self._session_started_monotonic = None
        self._cloud_reporter = CloudReporter.from_env()
        self._recent_tool_outcomes = deque(maxlen=8)
        self._pending_grounding_outcome = None

    def _report_event(self, event_type, payload=None):
        if not self._cloud_reporter:
            return
        try:
            self._cloud_reporter.event(event_type, payload or {})
        except Exception:
            pass

    def _normalize_tool_result(self, result):
        normalized = dict(result) if isinstance(result, dict) else {"status": "success", "value": str(result)}

        status = str(normalized.get("status", "success")).strip().lower()
        target_verified = bool(normalized.get("target_verified", False))
        requires_visual_confirmation = bool(
            normalized.get("requires_visual_confirmation", not target_verified)
        )
        action_status = str(normalized.get("action_status", "")).strip().lower()

        if status == "error":
            action_status = "failed"
            target_verified = False
            requires_visual_confirmation = False
        elif not action_status:
            action_status = "confirmed" if target_verified else "executed_unverified"

        normalized["status"] = status
        normalized["target_verified"] = target_verified
        normalized["requires_visual_confirmation"] = requires_visual_confirmation
        normalized["action_status"] = action_status

        msg = normalized.get("message")
        if isinstance(msg, str) and len(msg) > 280:
            normalized["message"] = msg[:280] + "...<truncated>"

        return normalized

    def _record_tool_outcome(self, tool_name, result):
        outcome = {
            "name": str(tool_name),
            "status": str(result.get("status", "success")).lower(),
            "action_status": str(result.get("action_status", "executed_unverified")).lower(),
            "target_verified": bool(result.get("target_verified", False)),
            "requires_visual_confirmation": bool(result.get("requires_visual_confirmation", True)),
            "message": str(result.get("message", ""))[:220],
        }
        self._recent_tool_outcomes.append(outcome)
        self._pending_grounding_outcome = outcome

    def _enforce_grounded_output(self, text):
        if not text:
            return text
        outcome = self._pending_grounding_outcome
        if not outcome:
            return text

        lowered = text.lower()
        assertive_markers = (
            "clicked",
            "switched",
            "focused",
            "opened",
            "closed",
            "typed",
            "scrolled",
            "done",
            "completed",
            "now on",
            "i have",
            "i did",
        )

        if outcome["status"] == "error":
            if any(m in lowered for m in assertive_markers):
                msg = outcome.get("message") or "tool error"
                safe = f"I could not complete `{outcome['name']}` due to tool error: {msg}."
                self._report_event("grounding_override", {"reason": "tool_error", "tool": outcome["name"]})
                return safe
            return text

        if outcome["action_status"] != "confirmed" and any(m in lowered for m in assertive_markers):
            safe = f"I attempted `{outcome['name']}`, but it is not visually verified yet. Please confirm what you see."
            self._report_event("grounding_override", {"reason": "unverified_action", "tool": outcome["name"]})
            return safe

        return text

    async def start(self):
        print("\n JavPI Voice AI - Listening ...\n")

        self.mic.start_recording()
        self.speaker.start_playback()
        self.running = True
        self._session_started_monotonic = time.monotonic()
        retry_delay = 2
        if self._cloud_reporter:
            try:
                self._cloud_reporter.start_session(
                    metadata={"runtime": "desktop", "resumption": self._use_session_resumption},
                    source="desktop",
                    app_version="0.1.0",
                )
            except Exception:
                pass
        self._report_event("app_start")

        while self.running:
            try:
                retry_delay = 2
                await self._run_session()
            except Exception as e:
                if not self.running:
                    break
                self._report_event(
                    "session_error",
                    {"type": type(e).__name__, "message": str(e)[:400]},
                )
                if "1011" in str(e) or "1006" in str(e):
                    print(f"[RECONNECT] Server disconnected, reconnecting in {retry_delay}s...")
                else:
                    print(f"[WARN] Session error ({type(e).__name__}: {e}), reconnecting in {retry_delay}s...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 30)

    async def _run_session(self):
        self.gemini = GeminiLiveClient(api_key=self.api_key, tools=self._tools)
        self._interrupting = False
        self._speech_hits = 0
        self._speech_misses = 0
        session_handle = self._session_handle if self._use_session_resumption else None
        await self.gemini.connect(session_handle=session_handle)
        print("[OK] Connected\\n")
        self._report_event("gemini_connected", {"resumed": bool(session_handle)})

        mic_task = asyncio.create_task(self._mic_loop())
        recv_task = asyncio.create_task(self._receive_loop())
        screen_task = asyncio.create_task(self._screen_loop())

        try:
            done, pending = await asyncio.wait(
                [mic_task, recv_task, screen_task],
                return_when=asyncio.FIRST_EXCEPTION,
            )
            for task in pending:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            for task in done:
                exc = task.exception()
                if exc:
                    raise exc
        finally:
            mic_task.cancel()
            recv_task.cancel()
            screen_task.cancel()

    async def stop(self):
        self.running = False
        duration_sec = None
        if self._session_started_monotonic is not None:
            duration_sec = max(0, int(time.monotonic() - self._session_started_monotonic))
        self._report_event("app_stop", {"duration_sec": duration_sec})

        if self.gemini:
            await self.gemini.disconnect()
        self.mic.stop_recording()
        self.speaker.stop_playback()

        if self._cloud_reporter:
            try:
                self._cloud_reporter.end_session(
                    status="completed",
                    summary={"duration_sec": duration_sec},
                )
                self._cloud_reporter.close(drain_sec=1.2)
            except Exception:
                pass

    async def _send_screenshot(self):
        if not self.gemini:
            return
        try:
            async with self._screen_send_lock:
                frame = await asyncio.get_event_loop().run_in_executor(None, self.screen.capture_full)
                img = Image.fromarray(frame)
                buf = io.BytesIO()
                # Keep native frame geometry so model coordinates map 1:1 to screen tools.
                img.save(buf, format="JPEG", quality=88)
                await self.gemini.send_image(buf.getvalue(), mime_type="image/jpeg")
                self._last_screen_sent_ts = time.monotonic()
        except Exception:
            pass

    async def _screen_loop(self):
        try:
            while self.running:
                await self._send_screenshot()
                await asyncio.sleep(self._screen_interval_sec)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[ERROR] Screen loop: {type(e).__name__}: {e}")
            raise

    def _bytes_to_waveform(self, audio_bytes):
        pcm = np.frombuffer(audio_bytes, dtype=np.int16)
        if pcm.size == 0:
            return None
        return torch.from_numpy(pcm.astype(np.float32) / 32768.0)

    def _append_speech_window(self, chunk):
        self._speech_window.append(chunk)
        self._speech_window_len += chunk.numel()
        while self._speech_window and self._speech_window_len > self._speech_window_samples:
            dropped = self._speech_window.popleft()
            self._speech_window_len -= dropped.numel()

    def _current_speech_window(self):
        if not self._speech_window:
            return None
        if len(self._speech_window) == 1:
            return self._speech_window[0]
        return torch.cat(list(self._speech_window))

    def _rms_db(self, waveform):
        rms = torch.sqrt(torch.mean(waveform.pow(2)) + 1e-10)
        return 20.0 * torch.log10(rms + 1e-10).item()

    def _speech_band_ratio(self, waveform):
        if waveform.numel() < 256:
            return 0.0

        window = torch.hann_window(waveform.numel(), dtype=waveform.dtype)
        spec = torch.fft.rfft(waveform * window)
        power = spec.abs().pow(2)
        if power.numel() == 0:
            return 0.0

        freqs = torch.fft.rfftfreq(waveform.numel(), d=1.0 / self.mic.sample_rate)
        band_mask = (freqs >= 85.0) & (freqs <= 3500.0)
        total = power.sum().item() + 1e-10
        speech = power[band_mask].sum().item()
        return speech / total

    def _vad_speech_present(self, waveform):
        try:
            trimmed = torchaudio.functional.vad(
                waveform,
                sample_rate=self.mic.sample_rate,
                trigger_level=6.0,
            )
            return trimmed.numel() >= int(0.08 * self.mic.sample_rate)
        except Exception:
            return False

    def _detect_speech_for_interrupt(self, audio_bytes, update_noise, strict=False):
        chunk = self._bytes_to_waveform(audio_bytes)
        if chunk is None:
            return False

        self._append_speech_window(chunk)
        window = self._current_speech_window()
        if window is None or window.numel() < 320:
            return False

        rms_db = self._rms_db(window)
        if update_noise:
            self._noise_floor_db = (
                self._noise_alpha * self._noise_floor_db
                + (1.0 - self._noise_alpha) * rms_db
            )
            self._noise_floor_db = max(-90.0, min(-20.0, self._noise_floor_db))

        band_ratio = self._speech_band_ratio(window)
        snr_db = rms_db - self._noise_floor_db
        min_rms_db = self._min_rms_db + (2.0 if strict else 0.0)
        min_snr_db = self._snr_threshold_db + (3.0 if strict else 0.0)
        min_band_ratio = self._speech_band_ratio_threshold + (0.05 if strict else 0.0)

        if rms_db < min_rms_db:
            return False
        if snr_db < min_snr_db:
            return False
        if band_ratio < min_band_ratio:
            return False

        vad_ok = self._vad_speech_present(window)
        if vad_ok:
            return True

        if strict:
            # In speaker-active mode, keep echo protection but allow natural barge-in
            # when VAD misses (common on softer voices / far mics).
            return snr_db >= (self._snr_threshold_db + 6.0) and band_ratio >= (self._speech_band_ratio_threshold + 0.02)

        # Fallback when torchaudio VAD is overly conservative on some mics.
        return snr_db >= (self._snr_threshold_db + 4.0) and band_ratio >= 0.50

    def _clean_transcript_text(self, text):
        if not text:
            return ""
        cleaned = re.sub(r"(?i)<\s*noise\s*>|\[\s*noise\s*\]|\(\s*noise\s*\)|<\s*ctrl\d+\s*>", " ", text)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        cleaned = self._repair_fragmented_words(cleaned)
        if not cleaned:
            return ""
        # English-only display path: hide mostly non-ASCII transcriptions.
        ascii_ratio = sum(1 for c in cleaned if ord(c) < 128) / max(1, len(cleaned))
        if ascii_ratio < 0.70:
            return ""
        return cleaned


    def _repair_fragmented_words(self, text):
        tokens = text.split()
        if len(tokens) < 2:
            return text

        stop_words = {
            "i", "to", "be", "in", "on", "at", "of", "an", "or", "if", "is", "it",
            "am", "we", "he", "she", "do", "go", "no", "up", "us", "my", "me", "a"
        }

        out = []
        i = 0
        n = len(tokens)
        while i < n:
            t = tokens[i]
            if (
                i + 1 < n
                and t.isalpha()
                and tokens[i + 1].isalpha()
                and len(t) <= 2
                and len(tokens[i + 1]) <= 2
                and t.lower() not in stop_words
            ):
                merged = t
                j = i + 1
                while j < n and tokens[j].isalpha() and len(tokens[j]) <= 2:
                    merged += tokens[j]
                    j += 1
                if len(merged) >= 4:
                    out.append(merged)
                    i = j
                    continue

            out.append(t)
            i += 1

        return " ".join(out)

    def _merge_transcript_piece(self, previous, piece):
        prev = (previous or "").strip()
        cur = (piece or "").strip()
        if not cur:
            return prev
        if not prev:
            return cur
        if cur == prev:
            return prev

        if cur.startswith(prev):
            return cur
        if prev.startswith(cur):
            return prev if len(cur) < int(0.85 * len(prev)) else cur
        if cur in prev:
            return prev
        if prev in cur:
            return cur

        max_overlap = min(len(prev), len(cur), 120)
        for n in range(max_overlap, 2, -1):
            if prev[-n:].lower() == cur[:n].lower():
                merged = prev + cur[n:]
                return re.sub(r"\s{2,}", " ", merged).strip()

        if cur[:1] in ",.;:!?)]}" or prev.endswith(("/", "-", "'")):
            return (prev + cur).strip()
        return (prev + " " + cur).strip()

    def _resample_to_mic_rate(self, waveform, source_rate):
        if waveform is None or waveform.numel() == 0:
            return None
        if int(source_rate) == int(self.mic.sample_rate):
            return waveform
        try:
            res = torchaudio.functional.resample(
                waveform.unsqueeze(0),
                int(source_rate),
                int(self.mic.sample_rate),
            )
            return res.squeeze(0)
        except Exception:
            arr = waveform.detach().cpu().numpy().astype(np.float32)
            n_out = max(1, int(round(arr.size * self.mic.sample_rate / float(source_rate))))
            x_old = np.linspace(0.0, 1.0, num=arr.size, endpoint=False)
            x_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
            out = np.interp(x_new, x_old, arr).astype(np.float32)
            return torch.from_numpy(out)

    def _is_echo_from_speaker(self, audio_bytes):
        mic = self._bytes_to_waveform(audio_bytes)
        if mic is None or mic.numel() < 256:
            return False

        recent = self.speaker.get_recent_audio(seconds=0.8)
        if recent is None or len(recent) < 256:
            return False

        ref = torch.from_numpy(np.asarray(recent, dtype=np.float32))
        ref = self._resample_to_mic_rate(ref, self.speaker.sample_rate)
        if ref is None or ref.numel() < 256:
            return False

        n = int(min(mic.numel(), ref.numel(), int(0.32 * self.mic.sample_rate)))
        if n < 256:
            return False

        x = mic[-n:].clone()
        y = ref[-n:].clone()

        x = x - torch.mean(x)
        y = y - torch.mean(y)

        nx = torch.norm(x).item()
        ny = torch.norm(y).item()
        if nx < 1e-6 or ny < 1e-6:
            return False

        def _corr(a, b):
            na = torch.norm(a).item()
            nb = torch.norm(b).item()
            if na < 1e-6 or nb < 1e-6:
                return 0.0
            return abs(torch.dot(a, b).item()) / (na * nb + 1e-9)

        best = _corr(x, y)
        lag = int(0.012 * self.mic.sample_rate)
        if n > (lag + 64):
            best = max(best, _corr(x[lag:], y[:-lag]), _corr(x[:-lag], y[lag:]))

        rms_x = torch.sqrt(torch.mean(x.pow(2)) + 1e-10).item()
        rms_y = torch.sqrt(torch.mean(y.pow(2)) + 1e-10).item()
        db_x = 20.0 * np.log10(rms_x + 1e-10)
        db_y = 20.0 * np.log10(rms_y + 1e-10)

        # Echo tends to correlate strongly and is not much louder than playback reference.
        return best >= 0.72 and db_x <= (db_y + 3.0)

    async def _mic_loop(self):
        try:
            while self.running:
                audio = await self.mic.get_audio_chunk_async(timeout=0.05)
                if not audio or not self.gemini:
                    continue

                speaker_active = self.speaker.is_speaking
                echo_likely = speaker_active and (not self._interrupting) and self._is_echo_from_speaker(audio)

                detected_speech = self._detect_speech_for_interrupt(
                    audio,
                    update_noise=(not speaker_active and not self._interrupting),
                    strict=(speaker_active and not self._interrupting),
                )
                if echo_likely:
                    detected_speech = False

                if speaker_active and not self._interrupting:
                    if detected_speech:
                        self._speech_hits += 1
                        self._speech_misses = 0
                    else:
                        self._speech_hits = 0

                    if self._speech_hits >= self._speech_trigger_frames:
                        self._interrupting = True
                        self._speech_hits = 0
                        self._speech_misses = 0
                        self.speaker.flush_signal()
                        self.speaker.clear_queue()
                        print("[INTERRUPT] User speech detected, yielding model turn.")
                    else:
                        continue

                if self._interrupting:
                    if detected_speech:
                        self._speech_misses = 0
                    else:
                        self._speech_misses += 1

                    await self.gemini.send_audio(audio, sample_rate=16000)

                    if self._speech_misses >= self._speech_release_frames:
                        self._interrupting = False
                        self._speech_misses = 0
                    continue

                await self.gemini.send_audio(audio, sample_rate=16000)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[ERROR] Mic loop: {type(e).__name__}: {e}")
            raise

    async def _handle_tool_call(self, tool_call):
        responses = []
        for fc in tool_call.function_calls:
            print(f"[TOOL] Tool: {fc.name}({dict(fc.args)})")
            start_ts = time.monotonic()
            raw_result = await execute_tool(fc)
            elapsed_ms = (time.monotonic() - start_ts) * 1000.0
            result = self._normalize_tool_result(raw_result)
            self._record_tool_outcome(fc.name, result)
            print(f"   -> {result}")
            if self._cloud_reporter:
                try:
                    self._cloud_reporter.tool_event(
                        name=fc.name,
                        args=dict(fc.args),
                        result=result,
                        elapsed_ms=elapsed_ms,
                    )
                except Exception:
                    pass
            responses.append(
                types.FunctionResponse(
                    id=fc.id,
                    name=fc.name,
                    response=result
                )
            )
        await self.gemini.send_tool_response(function_responses=responses)

        await asyncio.sleep(0.5)
        await self._send_screenshot()

    async def _receive_loop(self):
        latest_input = ""
        latest_output = ""
        try:
            while self.running:
                async for msg in self.gemini.session.receive():
                    if not self.running:
                        return

                    if self._use_session_resumption and hasattr(msg, 'session_resumption_update') and msg.session_resumption_update:
                        update = msg.session_resumption_update
                        if getattr(update, 'resumable', False) and getattr(update, 'new_handle', None):
                            self._session_handle = update.new_handle

                    if getattr(msg, 'tool_call', None):
                        await self._handle_tool_call(msg.tool_call)
                        continue

                    sc = msg.server_content
                    if not sc:
                        continue

                    if getattr(sc, 'input_transcription', None) and sc.input_transcription.text:
                        if (time.monotonic() - self._last_screen_sent_ts) > 0.9:
                            await self._send_screenshot()
                        cleaned_input = self._clean_transcript_text(sc.input_transcription.text)
                        if cleaned_input:
                            latest_input = self._merge_transcript_piece(latest_input, cleaned_input)

                    if getattr(sc, 'output_transcription', None) and sc.output_transcription.text:
                        cleaned_output = self._clean_transcript_text(sc.output_transcription.text)
                        if cleaned_output:
                            latest_output = self._merge_transcript_piece(latest_output, cleaned_output)

                    if sc.model_turn:
                        for part in sc.model_turn.parts:
                            if part.inline_data:
                                raw = np.frombuffer(part.inline_data.data, dtype='int16')
                                audio = raw.astype(np.float32) / 32768.0
                                try:
                                    mt = getattr(part.inline_data, "mime_type", "")
                                    if "rate=" in mt:
                                        rate = int(mt.split("rate=")[-1])
                                    else:
                                        rate = 24000
                                except Exception:
                                    rate = 24000
                                if rate != self.speaker.sample_rate:
                                    try:
                                        tensor = torch.from_numpy(audio).unsqueeze(0)
                                        res = torchaudio.functional.resample(tensor, rate, self.speaker.sample_rate)
                                        audio = res.squeeze(0).numpy()
                                    except Exception:
                                        pass
                                self.speaker.queue_audio(audio)

                    if getattr(sc, 'turn_complete', False):
                        self.speaker.clear_queue()
                        self.speaker.flush_signal()
                        full_input = latest_input.strip()
                        full_output = latest_output.strip()
                        full_input = re.sub(r"\s+([,.;:!?])", r"\1", full_input)
                        full_output = re.sub(r"\s+([,.;:!?])", r"\1", full_output)
                        full_output = self._enforce_grounded_output(full_output)
                        if full_input:
                            print(f"You: {full_input}")
                        if full_output:
                            print(f"Gemini: {full_output}")
                        latest_input = ""
                        latest_output = ""
                        self._pending_grounding_outcome = None

        except asyncio.CancelledError:
            pass
        except Exception as e:
            if "1011" not in str(e) and "1006" not in str(e):
                print(f"[ERROR] Receive loop: {type(e).__name__}: {e}")
            raise


