from __future__ import annotations

from functools import wraps
from typing import Any, Callable, TypeVar

T = TypeVar("T")


def validate_params(**validators: Callable[[Any], tuple[bool, str | None]]):
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> T:
            from inspect import signature

            bound_args = signature(func).bind(*args, **kwargs)
            bound_args.apply_defaults()
            _validate_bound_arguments(bound_args.arguments, validators)
            return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> T:
            from inspect import signature

            bound_args = signature(func).bind(*args, **kwargs)
            bound_args.apply_defaults()
            _validate_bound_arguments(bound_args.arguments, validators)
            return func(*args, **kwargs)

        import inspect

        return async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper

    return decorator


def _validate_bound_arguments(arguments: dict[str, Any], validators: dict[str, Callable[[Any], tuple[bool, str | None]]]) -> None:
    for param_name, validator in validators.items():
        if param_name in arguments:
            value = arguments[param_name]
            is_valid, error_msg = validator(value)
            if not is_valid:
                raise ValueError(f"参数验证失败: {param_name} - {error_msg}")
