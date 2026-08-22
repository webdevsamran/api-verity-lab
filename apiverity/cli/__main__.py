"""Allow ``python -m apiverity.cli`` invocation."""
import sys

from apiverity.cli.main import main

sys.exit(main())