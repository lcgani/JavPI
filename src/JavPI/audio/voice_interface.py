"""Voice interface connecting microphone to Gemini Live API."""

import asyncio
import logging
from typing import AsyncIterator, Optional

from ..gemini.client import GeminiLiveClient, GeminiError
from .capture import AudioCapture, AudioCaptureError

logger = logging.getLogger(__name__)


class VoiceInterfaceError(Exception):
    """Raised when voice interface operations fail."""
    pass


class VoiceInterface:
    """Manages bidirectional voice communication with Gemini."""

    def __init__(
        self,
        gemini_client: GeminiLiveClient,
        sample_rate: int = 16000,
        device: Optional[int] = None
    ):
        """Initialize voice interface.
        
        Args:
            gemini_client: Gemini Live API client
            sample_rate: Audio sample rate (16000 for Gemini)
            device: Audio device index (None for default)
        """
        self.gemini_client = gemini_client
        self.audio_capture = AudioCapture(
            sample_rate=sample_rate,
            channels=1,
            dtype='int16',
            device=device
        )
        
        self.is_active = False
        self._input_task: Optional[asyncio.Task] = None
        self._output_task: Optional[asyncio.Task] = None
        self._should_stop = False
        
        logger.info("VoiceInterface initialized")

    async def start(self) -> None:
        """Start voice interface (mic input + audio output).
        
        Raises:
            VoiceInterfaceError: If start fails
        """
        if self.is_active:
            logger.warning("Voice interface already active")
            return
        
        try:
            if not self.gemini_client._connected:
                await self.gemini_client.connect()
            
            self.audio_capture.start_recording()
            
            self._should_stop = False
            self._input_task = asyncio.create_task(self._stream_input())
            self._output_task = asyncio.create_task(self._stream_output())
            
            self.is_active = True
            logger.info("Voice interface started")
        
        except AudioCaptureError as e:
            raise VoiceInterfaceError(f"Failed to start audio capture: {e}") from e
        except GeminiError as e:
            raise VoiceInterfaceError(f"Failed to connect to Gemini: {e}") from e
        except Exception as e:
            raise VoiceInterfaceError(f"Failed to start voice interface: {e}") from e

    async def stop(self) -> None:
        """Stop voice interface."""
        if not self.is_active:
            logger.warning("Voice interface not active")
            return
        
        try:
            self._should_stop = True
            
            if self._input_task:
                self._input_task.cancel()
                try:
                    await self._input_task
                except asyncio.CancelledError:
                    pass
            
            if self._output_task:
                self._output_task.cancel()
                try:
                    await self._output_task
                except asyncio.CancelledError:
                    pass
            
            self.audio_capture.stop_recording()
            
            self.is_active = False
            logger.info("Voice interface stopped")
        
        except Exception as e:
            logger.error(f"Error stopping voice interface: {e}")

    async def _stream_input(self) -> None:
        """Stream microphone input to Gemini (runs continuously)."""
        logger.info("Started input streaming")
        
        try:
            while not self._should_stop:
                audio_chunk = await self.audio_capture.get_audio_chunk_async(timeout=0.5)
                
                if audio_chunk:
                    try:
                        await self.gemini_client.send_audio(
                            audio_chunk,
                            sample_rate=self.audio_capture.sample_rate
                        )
                    except GeminiError as e:
                        logger.error(f"Failed to send audio to Gemini: {e}")
                        await asyncio.sleep(1.0)
        
        except asyncio.CancelledError:
            logger.info("Input streaming cancelled")
        except Exception as e:
            logger.error(f"Error in input streaming: {e}")

    async def _stream_output(self) -> None:
        """Stream Gemini audio output to speakers (runs continuously)."""
        logger.info("Started output streaming")
        
        try:
            async for audio_chunk in self.gemini_client.receive_audio():
                if self._should_stop:
                    break
                
                logger.debug(f"Received audio chunk: {len(audio_chunk)} bytes")
        
        except asyncio.CancelledError:
            logger.info("Output streaming cancelled")
        except GeminiError as e:
            logger.error(f"Error receiving audio from Gemini: {e}")
        except Exception as e:
            logger.error(f"Error in output streaming: {e}")

    async def send_text_prompt(self, text: str) -> None:
        """Send text prompt to Gemini (alternative to voice).
        
        Args:
            text: Text prompt to send
        """
        if not self.is_active:
            raise VoiceInterfaceError("Voice interface not active")
        
        logger.info(f"Sending text prompt: {text[:50]}...")

    async def receive_text_response(self) -> AsyncIterator[str]:
        """Receive text transcription/response from Gemini.
        
        Yields:
            Text chunks from Gemini
        """
        if not self.is_active:
            raise VoiceInterfaceError("Voice interface not active")
        
        async for text in self.gemini_client.receive_text():
            yield text

    def list_audio_devices(self) -> list[dict]:
        """List available audio input devices.
        
        Returns:
            List of device info dictionaries
        """
        return self.audio_capture.list_devices()

    def get_default_device(self) -> Optional[dict]:
        """Get default audio input device.
        
        Returns:
            Device info or None
        """
        return self.audio_capture.get_default_device()

    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.stop()
