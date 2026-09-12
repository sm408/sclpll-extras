"""Reading a credential from inside a workflow.

Two functions, because that is the whole surface. A workflow needs to *use* a secret;
storing and listing them is `sclpl secret`, which is a job a person does once rather
than something a run does.

**The value never reaches a log.** Redaction happens in the reporter, keyed on the set of
resolved secret values, so this can return the real thing and every sink still shows it
redacted. A component that forgets to redact cannot leak, because it never had the
chance to.
"""

from __future__ import annotations

import contextlib

from sclpl.errors import ValidationError
from sclpl.ext.functions import function
from sclpl.render.redact import TooShortToRedact
from sclpl.render.reporter import active_reporter
from sclpl.state import secrets as store


@function("secret", builtin=True)
def secret(name: str, *, env: str = "default") -> str:
    """The named credential. Fails loudly rather than sending an empty header.

    A missing secret is an error, not an empty string. A request authenticated with
    nothing gets a 401 that reads as "the credential was wrong", which sends the reader
    to the wrong place entirely.
    """
    found = store.get(name, env=env)
    if found is None:
        raise ValidationError(
            f"no secret named {name!r}",
            remedies=[
                f"sclpl secret set {name}",
                f"or set SCLPL_SECRET_{name.upper().replace('-', '_')} for CI",
            ],
        )
    # Registering here, at the one place the real value comes into existence, is what
    # makes the module docstring's promise true rather than aspirational: nothing
    # called `Reporter.secret()` before this, so every sink saw the value in the clear.
    reporter = active_reporter()
    if reporter is not None:
        # A secret too short to redact safely (see redact.MIN_LENGTH) is a workflow
        # author's problem, not a reason to fail a request that already succeeded.
        with contextlib.suppress(TooShortToRedact):
            reporter.secret(found)
    return found


@function("has_secret", builtin=True)
def has_secret(name: str, *, env: str = "default") -> bool:
    """Whether a credential is available, without reading it.

    For a workflow that does something different when there is none -- a public
    endpoint, a smaller page size -- rather than failing.
    """
    return store.get(name, env=env) is not None
