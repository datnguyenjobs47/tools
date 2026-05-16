import time
import asyncio
from typing import Optional

from playwright.async_api import Page, Frame


class RecaptchaSolver:
    """Solve reCAPTCHA v2 bằng JS inject trong browser.
    
    Flow:
    - Playwright: click checkbox, lấy frame reference
    - JavaScript (trong browser): click audio button, fetch audio src
    - Python: download mp3, transcribe qua SpeechRecognition
    - JavaScript (trong browser): fill answer, click verify
    - Playwright: kiểm tra solved
    """

    TIMEOUT_STANDARD = 7_000
    TIMEOUT_SHORT    = 1_000

    def __init__(self, page: Page) -> None:
        self.page = page

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def solveCaptcha(self) -> None:
        # 1. Click checkbox
        checkbox_frame = await self._get_frame_by_title("reCAPTCHA")
        await checkbox_frame.wait_for_selector(
            ".rc-anchor-content", timeout=self.TIMEOUT_STANDARD
        )
        # Dùng JS click để tránh Playwright actionable check
        await checkbox_frame.evaluate(
            "document.querySelector('.rc-anchor-content').click()"
        )
        await self.page.wait_for_timeout(800)

        if await self.is_solved():
            return

        # 2. Lấy challenge frame
        challenge_frame = await self._get_frame_by_url("bframe")

        # 3. Dùng JS click audio button (bypass visibility check)
        await challenge_frame.evaluate("""
            document.getElementById('recaptcha-audio-button').click()
        """)
        await self.page.wait_for_timeout(1500)

        if await self.is_detected(challenge_frame):
            raise Exception("reCAPTCHA detected bot — thử đổi IP/proxy")

        # 4. Lấy audio src bằng JS
        src = await challenge_frame.evaluate("""
            (() => {
                const el = document.getElementById('audio-source');
                return el ? el.src : null;
            })()
        """)
        if not src:
            raise Exception("Không lấy được audio source URL")

        # 5. Download + transcribe (Python side)
        text = await asyncio.to_thread(self._process_audio, src)
        print(f"[INFO] Transcribed: {text!r}")

        # 6. Fill answer + submit bằng JS
        await challenge_frame.evaluate(f"""
            (() => {{
                const input = document.getElementById('audio-response');
                const btn   = document.getElementById('recaptcha-verify-button');
                
                // Set value và trigger React/Vue event nếu có
                const nativeInput = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value'
                );
                nativeInput.set.call(input, '{text.lower()}');
                input.dispatchEvent(new Event('input',  {{ bubbles: true }}));
                input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                
                btn.click();
            }})()
        """)
        await self.page.wait_for_timeout(800)

        if not await self.is_solved():
            raise Exception("Captcha answer rejected")

        print("[INFO] reCAPTCHA solved!")

    # ------------------------------------------------------------------
    # Audio processing (Python side)
    # ------------------------------------------------------------------

    def _process_audio(self, audio_url: str) -> str:
        import os, urllib.request, random, pydub, speech_recognition

        TEMP = os.getenv("TEMP") if os.name == "nt" else "/tmp"
        mp3  = os.path.join(TEMP, f"rc_{random.randrange(1, 10_000)}.mp3")
        wav  = os.path.join(TEMP, f"rc_{random.randrange(1, 10_000)}.wav")

        try:
            urllib.request.urlretrieve(audio_url, mp3)
            pydub.AudioSegment.from_mp3(mp3).export(wav, format="wav")

            r = speech_recognition.Recognizer()
            with speech_recognition.AudioFile(wav) as src:
                audio = r.record(src)
            return r.recognize_google(audio)
        finally:
            for p in (mp3, wav):
                try:
                    os.remove(p)
                except OSError:
                    pass

    # ------------------------------------------------------------------
    # Frame finders
    # ------------------------------------------------------------------

    async def _get_frame_by_title(self, title_contains: str) -> Frame:
        """Tìm anchor frame — URL chứa 'anchor'."""
        deadline = time.time() + self.TIMEOUT_STANDARD / 1000
        while time.time() < deadline:
            for frame in self.page.frames:
                url = frame.url or ""
                if "anchor" in url and "recaptcha" in url:
                    return frame
            await self.page.wait_for_timeout(100)
        raise Exception("reCAPTCHA anchor frame không tìm thấy")

    async def _get_frame_by_url(self, url_contains: str) -> Frame:
        deadline = time.time() + self.TIMEOUT_STANDARD / 1000
        while time.time() < deadline:
            for frame in self.page.frames:
                if url_contains in (frame.url or ""):
                    return frame
            await self.page.wait_for_timeout(100)
        await self.debug_frames()
        raise Exception(f"Frame URL '{url_contains}' không tìm thấy")

    # ------------------------------------------------------------------
    # State checks
    # ------------------------------------------------------------------

    async def is_solved(self) -> bool:
        try:
            checkbox_frame = await self._get_frame_by_title("reCAPTCHA")
            # Dùng JS để check style thay vì Playwright locator
            return await checkbox_frame.evaluate("""
                (() => {
                    const el = document.querySelector('.recaptcha-checkbox-checkmark');
                    return el ? el.hasAttribute('style') : false;
                })()
            """)
        except Exception:
            return False

    async def is_detected(self, frame: Frame) -> bool:
        try:
            return await frame.evaluate("""
                (() => {
                    const els = document.querySelectorAll('*');
                    for (const el of els) {
                        if (el.textContent.trim() === 'Try again later' 
                            && el.offsetParent !== null) {
                            return true;
                        }
                    }
                    return false;
                })()
            """)
        except Exception:
            return False

    async def get_token(self) -> Optional[str]:
        try:
            return await self.page.evaluate("""
                (() => {
                    const el = document.getElementById('g-recaptcha-response');
                    return el ? el.value : null;
                })()
            """)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Debug
    # ------------------------------------------------------------------

    async def debug_frames(self) -> None:
        print(f"\n[DEBUG] Tổng số frames: {len(self.page.frames)}")
        for i, frame in enumerate(self.page.frames):
            try:
                title = await frame.title()
            except Exception:
                title = "(error)"
            print(f"  [{i}] url  = {frame.url!r}")
            print(f"       title = {title!r}")