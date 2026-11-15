"""Run the same CLI owner when invoked with ``python -m dm_engine``."""
from .cli import main
raise SystemExit(main())
