import pytest

from app.domain.errors import ValidationError
from app.domain.models import ResourceSpec


def test_resource_spec_validation_success():
    spec = ResourceSpec(cpu=2, memory_mib=2048, disk_gib=40)
    spec.validate()


@pytest.mark.parametrize(
    "cpu,memory_mib,disk_gib",
    [
        (0, 1024, 20),
        (1, 0, 20),
        (1, 1024, 0),
    ],
)
def test_resource_spec_validation_fail(cpu: int, memory_mib: int, disk_gib: int):
    spec = ResourceSpec(cpu=cpu, memory_mib=memory_mib, disk_gib=disk_gib)
    with pytest.raises(ValidationError):
        spec.validate()
