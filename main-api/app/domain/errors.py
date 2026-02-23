class DomainError(Exception):
    code = "DOMAIN_ERROR"


class ForbiddenError(DomainError):
    code = "FORBIDDEN"


class ValidationError(DomainError):
    code = "VALIDATION_ERROR"


class CapacityExceededError(DomainError):
    code = "CAPACITY_EXCEEDED"


class QuotaExceededError(DomainError):
    code = "QUOTA_EXCEEDED"


class QuotaConflictError(DomainError):
    code = "QUOTA_CONFLICT"


class TenantInactiveError(DomainError):
    code = "TENANT_INACTIVE"


class NotFoundError(DomainError):
    code = "VM_NOT_FOUND"


class InstanceNotFoundError(DomainError):
    code = "INSTANCE_NOT_FOUND"


class TaskNotFoundError(DomainError):
    code = "TASK_NOT_FOUND"


class TenantNotFoundError(DomainError):
    code = "TENANT_NOT_FOUND"


class UserNotFoundError(DomainError):
    code = "USER_NOT_FOUND"


class AuditLogNotFoundError(DomainError):
    code = "AUDIT_LOG_NOT_FOUND"


class ConflictError(DomainError):
    code = "CONFLICT"


class VmCommandError(DomainError):
    code = "QEMU_ERROR"


class TimeoutError(DomainError):
    code = "TIMEOUT"
