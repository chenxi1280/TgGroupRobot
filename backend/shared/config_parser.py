"""配置解析工具类

提供统一的配置文本解析接口，支持键值对和行格式配置。
"""
from __future__ import annotations

import structlog
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

log = structlog.get_logger(__name__)


@dataclass
class ParseResult:
    """配置解析结果

    Args:
        success: 是否解析成功
        data: 解析后的数据字典
        error: 错误信息（失败时）
    """
    success: bool
    data: dict = field(default_factory=dict)
    error: str = ""

    @classmethod
    def ok(cls, data: dict | None = None) -> "ParseResult":
        """创建成功结果

        Args:
            data: 解析后的数据

        Returns:
            ParseResult: 成功结果
        """
        return cls(success=True, data=data or {})

    @classmethod
    def fail(cls, error: str) -> "ParseResult":
        """创建失败结果

        Args:
            error: 错误信息

        Returns:
            ParseResult: 失败结果
        """
        return cls(success=False, error=error)


class BaseConfigParser(ABC):
    """配置解析器基类

    定义配置解析的通用接口。
    """

    @abstractmethod
    def parse(self, text: str) -> ParseResult:
        """解析配置文本

        Args:
            text: 配置文本

        Returns:
            ParseResult: 解析结果
        """
        raise NotImplementedError


class KeyValueConfigParser(BaseConfigParser):
    """键值对配置解析器

    解析格式为 "key: value" 的配置文本。

    示例:
        定时类型: daily
        初始延迟: 60
        是否重复: 是
    """

    def __init__(
        self,
        required_keys: list[str] | None = None,
        optional_keys: list[str] | None = None,
        trim_whitespace: bool = True,
    ) -> None:
        """初始化解析器

        Args:
            required_keys: 必需的键列表
            optional_keys: 可选的键列表（用于验证）
            trim_whitespace: 是否去除空白字符
        """
        self.required_keys = required_keys or []
        self.optional_keys = optional_keys or []
        self.trim_whitespace = trim_whitespace

    def parse(self, text: str) -> ParseResult:
        """解析键值对配置

        Args:
            text: 配置文本

        Returns:
            ParseResult: 解析结果
        """
        try:
            result = self._parse_lines(text)
            if isinstance(result, ParseResult):
                return result

            # 验证必需的键
            missing_keys = [k for k in self.required_keys if k not in result]
            if missing_keys:
                return ParseResult.fail(f"缺少必需的配置项: {', '.join(missing_keys)}")

            return ParseResult.ok(result)

        except Exception as e:
            log.exception("config_parse_error")
            return ParseResult.fail(f"解析失败: {str(e)}")

    def _parse_lines(self, text: str) -> dict[str, str] | ParseResult:
        result: dict[str, str] = {}
        for raw_line in text.strip().splitlines():
            line = raw_line.strip() if self.trim_whitespace else raw_line
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                return ParseResult.fail(f"配置行格式错误，缺少冒号: {line}")
            key, value = line.split(":", 1)
            if self.trim_whitespace:
                key, value = key.strip(), value.strip()
            result[key] = value
        return result


class MultiLineConfigParser(BaseConfigParser):
    """多行配置解析器

    解析包含多行内容的配置，支持键值对和纯文本内容的混合格式。

    示例:
        这是第一行内容
        这是第二行内容
        配置项: 值
    """

    def __init__(
        self,
        config_marker: str = ":",
        content_first: bool = True,
    ) -> None:
        """初始化解析器

        Args:
            config_marker: 配置项标记（默认 ":"）
            content_first: 内容是否在配置项之前
        """
        self.config_marker = config_marker
        self.content_first = content_first

    def parse(self, text: str) -> ParseResult:
        """解析多行配置

        Args:
            text: 配置文本

        Returns:
            ParseResult: 解析结果
        """
        try:
            return ParseResult.ok(self._parse_lines(text))

        except Exception as e:
            log.exception("multiline_config_parse_error")
            return ParseResult.fail(f"解析失败: {str(e)}")

    def _parse_lines(self, text: str) -> dict[str, object]:
        content_lines: list[str] = []
        config: dict[str, str] = {}
        for raw_line in text.strip().splitlines():
            line = raw_line.strip()
            if self.config_marker not in line:
                if self.content_first:
                    content_lines.append(line)
                continue
            key, value = line.split(self.config_marker, 1)
            config[key.strip()] = value.strip()
        return {"content": "\n".join(content_lines).strip(), "config": config}


class DateTimeParser:
    """日期时间解析工具类

    提供常用的日期时间解析方法。
    """

    @staticmethod
    def parse_minutes(text: str) -> int | None:
        """解析分钟数

        支持格式: "60", "60m", "1h", "1h30m"

        Args:
            text: 时间文本

        Returns:
            int | None: 解析出的分钟数，失败返回 None
        """
        raw_text = text
        text = text.strip().lower()

        try:
            # 纯数字
            if text.isdigit():
                return int(text)

            total_minutes = 0

            # 解析小时和分钟
            if "h" in text:
                parts = text.split("h")
                if parts[0]:
                    total_minutes += int(parts[0]) * 60
                text = parts[1] if len(parts) > 1 else ""

            if "m" in text:
                parts = text.split("m")
                if parts[0]:
                    total_minutes += int(parts[0])

            if total_minutes > 0:
                return total_minutes
            log.warning("parse_minutes_failed", raw_value=raw_text)
            return None

        except (ValueError, IndexError):
            log.warning("parse_minutes_failed", raw_value=raw_text)
            return None

    @staticmethod
    def parse_datetime(text: str, format: str = "%Y-%m-%d %H:%M") -> datetime | None:
        """解析日期时间字符串

        Args:
            text: 日期时间文本
            format: 日期时间格式

        Returns:
            datetime | None: 解析出的日期时间，失败返回 None
        """
        try:
            return datetime.strptime(text.strip(), format)
        except ValueError:
            log.warning("parse_datetime_failed", raw_value=text, format=format)
            return None


class ConfigParser:
    """统一配置解析工具类

    提供静态方法访问各种解析器。
    """

    @staticmethod
    def parse_key_value(
        text: str,
        required_keys: list[str] | None = None,
    ) -> ParseResult:
        """解析键值对配置（快捷方法）

        Args:
            text: 配置文本
            required_keys: 必需的键列表

        Returns:
            ParseResult: 解析结果
        """
        parser = KeyValueConfigParser(required_keys=required_keys)
        return parser.parse(text)

    @staticmethod
    def parse_multi_line(text: str) -> ParseResult:
        """解析多行配置（快捷方法）

        Args:
            text: 配置文本

        Returns:
            ParseResult: 解析结果
        """
        parser = MultiLineConfigParser()
        return parser.parse(text)
