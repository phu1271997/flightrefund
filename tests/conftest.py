import pytest
from gltest import create_account


@pytest.fixture
def buyer():
    return create_account()


@pytest.fixture
def other():
    return create_account()
