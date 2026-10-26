import os
import pytest
from django.conf import settings

@pytest.fixture(autouse=True)
def configure_test_environment(settings):
    settings.ALLOW_HASH_PROJECTION_FALLBACK = True
    os.environ['ALLOW_HASH_PROJECTION_FALLBACK'] = 'True'
