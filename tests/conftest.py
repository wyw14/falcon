import functools
import http.client
import inspect
import pathlib
import sys

import pytest
from falcon import App, testing


@pytest.fixture(scope='function')
def util():
    return _SuiteUtils()


class _SuiteUtils:
    """Provides helper methods for test functions."""

    # defaults
    DEFAULT_TYPE = falcon.asgi.App  # for type hints in tests
