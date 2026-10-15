"""Allow ``python -m backup_sentinel``."""

from backup_sentinel.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
