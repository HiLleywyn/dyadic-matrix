"""PyInstaller entry point; the ordinary source command uses the same owner."""
from dm_engine.cli import main

raise SystemExit(main())
