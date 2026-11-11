"""The one OpenGrade handle of the tour: every app and script imports ``og`` from here.

``project`` is a name: the project is created on the platform the first time it is
needed. Nothing else to set up: tracing starts on the first ``@og.trace`` call, and a
platform that is down never breaks the apps (spans are dropped with one warning).
"""

from __future__ import annotations

from opengrade import Opengrade

from nimbus_apps import settings

og = Opengrade(project=settings.PROJECT, tracking_uri=settings.TRACKING_URI)
