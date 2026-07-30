"""Integration layer: where a domain and the platform are wired together.

**This package is not part of the platform, and it is not part of any domain.**
It is the only place allowed to know about both.

That separation is forced rather than tidy. A domain may not depend on the
platform (PADR-002), and the platform may not depend on a domain (PADR-013);
so the code that teaches the scheduler how to run Retail cannot live in either.
It lives here.

One package per domain. Adding Healthcare means adding ``eds/runners/healthcare/``
and changing nothing else - which is the claim the platform has been making
since P001, tested for the first time by the fact that Retail's runner needed
no platform change to exist.
"""
