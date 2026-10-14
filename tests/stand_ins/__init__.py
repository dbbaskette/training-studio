"""Stand-ins for the companion tools the runner calls, for tests only.

    slides      behaves like the harness-slides command line
    brand       behaves like a brand skill's companion command, for one made-up brand
    research    behaves like the harness-research command line

Each module's `stand_in()` gives the runner's own wrapper with its stand-in behind it, so
that no test needs Node, an installed skill or the network. Each StandIn says in its own
docstring where it is simpler than the real thing.
"""
import sys

import helpers

if str(helpers.REPO) not in sys.path:
    sys.path.insert(0, str(helpers.REPO))
