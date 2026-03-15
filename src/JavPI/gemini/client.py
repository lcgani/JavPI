from google import genai
from google.genai import types


class GeminiError(Exception):
    pass


class GeminiLiveClient:

    def __init__(
        self,
        api_key,
        model="gemini-2.5-flash-native-audio-preview-12-2025",
        tools=None,
    ):
        self.api_key = api_key
        self.model = model
        self.tools = tools or []
        self.session = None
        self._session_context = None
        self._connected = False
        self.client = genai.Client(api_key=self.api_key)

    def _system_instruction(self):
        parts = [
            "You are JavPI, a real-time desktop copilot with a calm, concise voice.",
            "Always respond in English.",
            "If user speech is unclear or non-English, ask for English clarification.",
            "Operate with this loop: Observe -> Act -> Verify.",
            "When the user asks to remember, save, bookmark, or keep something for later, use memory_save.",
            "When the user asks about something seen or saved earlier, use memory_search before answering from memory.",
            "Never guess screen facts.",
            "Only state labels/counts/actions visually confirmed in the latest frame.",
            "If uncertain, say you are unsure and request a recheck.",
            "If target_verified=false or requires_visual_confirmation=true,",
            "do not claim completion; say action attempted but not verified.",
            "If a tool reports status=error, clearly state failure with brief reason.",
            "Do not repeat failing actions in a loop; " +
            "change strategy or ask one concise question.",
        ]
        return " ".join(parts)

    async def _open_live_session(self, config_params):
        config = types.LiveConnectConfig(**config_params)
        self._session_context = self.client.aio.live.connect(
            model=self.model,
            config=config,
        )
        self.session = await self._session_context.__aenter__()
        self._connected = True

    async def connect(self, session_handle=None):
        config_params = {
            "response_modalities": ["AUDIO"],
            "input_audio_transcription": {},
            "output_audio_transcription": {},
            "system_instruction": self._system_instruction(),
        }

        if session_handle:
            config_params["session_resumption"] = {"handle": session_handle}

        if self.tools:
            config_params["tools"] = self.tools

        try:
            await self._open_live_session(config_params)
        except Exception as e:
            err = str(e).lower()
            if "system_instruction" in config_params and (
                "invalid argument" in err
                or "unexpected keyword" in err
                or "not implemented" in err
            ):
                fallback = dict(config_params)
                fallback.pop("system_instruction", None)
                try:
                    await self._open_live_session(fallback)
                    return
                except Exception as e2:
                    raise GeminiError(f"Connection failed: {e2}") from e2
            raise GeminiError(f"Connection failed: {e}") from e

    async def disconnect(self):
        if self._session_context and self.session:
            try:
                await self._session_context.__aexit__(None, None, None)
            except Exception:
                pass
        self._connected = False
        self.session = None
        self._session_context = None

    async def send_audio(self, audio_chunk, sample_rate=16000):
        if not self._connected or not self.session:
            raise GeminiError("Not connected")
        try:
            await self.session.send_realtime_input(
                audio=types.Blob(
                    data=audio_chunk,
                    mime_type=f"audio/pcm;rate={sample_rate}",
                )
            )
        except Exception as e:
            raise GeminiError(f"Audio send failed: {e}") from e

    async def send_tool_response(self, function_responses):
        if not self._connected or not self.session:
            raise GeminiError("Not connected")
        try:
            await self.session.send_tool_response(
                function_responses=function_responses
            )
        except Exception as e:
            raise GeminiError(f"Tool response failed: {e}") from e

    async def send_image(self, image_bytes, mime_type="image/jpeg"):
        if not self._connected or not self.session:
            raise GeminiError("Not connected")
        try:
            await self.session.send_realtime_input(
                video=types.Blob(data=image_bytes, mime_type=mime_type)
            )
        except Exception as e:
            raise GeminiError(f"Image send failed: {e}") from e
