class DomainError(Exception):
    code = "DOMAIN_ERROR"


class ValidationError(DomainError):
    code = "VALIDATION_ERROR"


class CapacityExceededError(DomainError):
    code = "CAPACITY_EXCEEDED"


class NotFoundError(DomainError):
    code = "VM_NOT_FOUND"


class ConflictError(DomainError):
    code = "CONFLICT"


class VmCommandError(DomainError):
    code = "QEMU_ERROR"


class TimeoutError(DomainError):
    code = "TIMEOUT"
