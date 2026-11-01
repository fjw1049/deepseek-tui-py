import pytest


@pytest.fixture
def complete_goal():
    def complete(service):
        return service.mark_complete("Verified")

    return complete
