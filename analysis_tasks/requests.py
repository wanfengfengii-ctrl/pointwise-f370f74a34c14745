from dataclasses import dataclass

class InvalidTaskRequest(ValueError):
    pass

@dataclass(frozen=True)
class WindowRequest:
    left: int
    right: int

@dataclass(frozen=True)
class FreezeRequest:
    task_id: str
    prefix: int
    windows: tuple

def validate_freeze_request(request, sequence_length):
    if not isinstance(request.task_id, str) or not request.task_id:
        raise InvalidTaskRequest("task ID must be a nonempty string")
    if type(request.prefix) is not int or not 0 <= request.prefix <= sequence_length:
        raise InvalidTaskRequest("invalid prefix")
    for window in request.windows:
        if (not isinstance(window, WindowRequest) or type(window.left) is not int
                or type(window.right) is not int
                or not 0 <= window.left <= window.right <= request.prefix):
            raise InvalidTaskRequest("invalid half-open window")
    return request

MAX_GROUP_PREFIX = 32
MAX_GROUP_WINDOWS = 2

def validate_group_freeze_request(request, sequence_lengths):
    if not isinstance(request.task_id, str) or not request.task_id:
        raise InvalidTaskRequest("task ID must be a nonempty string")
    if (type(request.prefix) is not int
            or not 0 <= request.prefix <= MAX_GROUP_PREFIX):
        raise InvalidTaskRequest("invalid group prefix")
    if any(request.prefix > length for length in sequence_lengths):
        raise InvalidTaskRequest("prefix exceeds sequence length")
    if len(request.windows) > MAX_GROUP_WINDOWS:
        raise InvalidTaskRequest("too many windows")
    for window in request.windows:
        if (not isinstance(window, WindowRequest) or type(window.left) is not int
                or type(window.right) is not int
                or not 0 <= window.left <= window.right <= request.prefix):
            raise InvalidTaskRequest("invalid half-open window")
    return request
