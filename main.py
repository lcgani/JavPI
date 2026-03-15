import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from JavPI.core import JavPI
from dotenv import load_dotenv

load_dotenv()

async def main():
    api_key = os.getenv('GEMINI_API_KEY')
    
    if not api_key:
        print("ERROR: GEMINI_API_KEY not set")
        return
    
    jarvy = JavPI(api_key=api_key)
    
    try:
        await jarvy.start()
    except KeyboardInterrupt:
        pass
    finally:
        await jarvy.stop()


if __name__ == "__main__":
    asyncio.run(main())
