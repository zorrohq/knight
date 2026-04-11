from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from knight.worker.config import settings
from knight.utils.db.bootstrap import initialize_database


def main() -> None:
    initialize_database(settings.database_url)


if __name__ == "__main__":
    main()
