import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))  # src modules import each other flat

from bot import bot          # noqa: E402
from config import TOKEN     # noqa: E402

if __name__ == "__main__":
    bot.run(TOKEN)
