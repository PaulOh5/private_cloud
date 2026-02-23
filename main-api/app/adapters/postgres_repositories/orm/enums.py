from __future__ import annotations

from enum import Enum

from sqlalchemy import Enum as SAEnum


class RoleEnum(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class InstanceStatusEnum(str, Enum):
    CREATING_PENDING = "creating_pending"
    UPDATING_PENDING = "updating_pending"
    STARTING_PENDING = "starting_pending"
    STOPPING_PENDING = "stopping_pending"
    DELETING_PENDING = "deleting_pending"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    DELETED = "deleted"


class TaskCommandEnum(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    START = "start"
    STOP = "stop"


class TaskStatusEnum(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_PENDING = "cancel_pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class OutboxStatusEnum(str, Enum):
    QUEUED = "queued"
    PUBLISHING = "publishing"
    SENT = "sent"
    FAILED = "failed"


def _str_enum(enum_cls, *, name: str):
    return SAEnum(
        enum_cls,
        values_callable=lambda items: [item.value for item in items],
        native_enum=False,
        validate_strings=True,
        name=name,
    )


ROLE_ENUM_TYPE = _str_enum(RoleEnum, name="role_enum")
INSTANCE_STATUS_ENUM_TYPE = _str_enum(InstanceStatusEnum, name="instance_status_enum")
TASK_COMMAND_ENUM_TYPE = _str_enum(TaskCommandEnum, name="task_command_enum")
TASK_STATUS_ENUM_TYPE = _str_enum(TaskStatusEnum, name="task_status_enum")
OUTBOX_STATUS_ENUM_TYPE = _str_enum(OutboxStatusEnum, name="outbox_status_enum")
