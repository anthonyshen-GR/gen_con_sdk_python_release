import struct
from datetime import datetime
from typing import List, Tuple, Optional, Dict, Any
import logging
import threading


class DASProtocol:
    MAGIC = b"das\r\n"
    MAGIC_LENGTH = len(MAGIC)

    MAX_PACKET_SIZE = 4096  # 最大数据包大小
    MAX_BUFFER_SIZE = 8192  # 最大缓冲区大小

    def __init__(self):
        self.logger = logging.getLogger("DASProtocol")

    @classmethod
    def find_packet(cls, data: bytes) -> Tuple[List[bytes], bytes]:
        packets = []
        buffer = data

        if len(buffer) > cls.MAX_BUFFER_SIZE:
            cls._log_warning(f"缓冲区过大: {len(buffer)}字节，清空缓冲区")
            return [], b""

        search_start = 0
        processed_count = 0

        while len(buffer) - search_start >= cls.MAGIC_LENGTH * 2:
            processed_count += 1
            if processed_count > 1000:
                cls._log_warning("检测到可能的无限循环，退出处理")
                break

            # 查找包头
            header_pos = buffer.find(cls.MAGIC, search_start)
            if header_pos == -1:
                remaining_data = buffer[search_start:]
                # 只在debug级别记录，避免过多警告
                cls._log_debug("not found header from index: {}, 保留 {} 字节数据".format(search_start, len(remaining_data)))
                break

            # 检查是否连续magic
            next_magic_pos = buffer.find(cls.MAGIC, header_pos + cls.MAGIC_LENGTH)
            if next_magic_pos == header_pos + cls.MAGIC_LENGTH:
                # 发现连续magic: das\r\ndas\r\n...
                cls._log_debug(f"发现连续magic，位置: {header_pos}")
                search_start = header_pos + cls.MAGIC_LENGTH  # 跳过第一个magic
                continue

            # 检查包头位置是否合理
            if header_pos > len(buffer) - cls.MAGIC_LENGTH * 2:
                # 数据不够完整，保留从包头开始的数据
                remaining_data = buffer[header_pos:]
                cls._log_debug(f"包头位置异常: {header_pos}, 保留 {len(remaining_data)} 字节数据")
                break

            footer_search_start = header_pos + cls.MAGIC_LENGTH
            footer_pos = buffer.find(cls.MAGIC, footer_search_start)
            if footer_pos == -1:
                # 没有找到包尾，保留从包头开始的数据，等待更多数据到达
                remaining_data = buffer[header_pos:]
                cls._log_debug(
                    "not found footer from index: {}, 保留 {} 字节数据等待完整数据包".format(footer_search_start, len(remaining_data))
                )
                break

            if footer_pos > len(buffer) - cls.MAGIC_LENGTH:
                # 包尾位置异常，保留从包头开始的数据
                remaining_data = buffer[header_pos:]
                cls._log_debug(
                    f"包尾位置异常: {footer_pos}, len buffer:{len(buffer)}, 保留 {len(remaining_data)} 字节数据"
                )
                break

            next_after_footer = footer_pos + cls.MAGIC_LENGTH
            if (
                next_after_footer < len(buffer)
                and buffer.find(cls.MAGIC, next_after_footer) == next_after_footer
            ):
                cls._log_debug("发现连续包尾magic，可能的数据包粘连")

            packet_end = footer_pos + cls.MAGIC_LENGTH
            full_packet = buffer[header_pos:packet_end]

            if len(full_packet) > cls.MAX_PACKET_SIZE:
                cls._log_warning(f"数据包过大: {len(full_packet)}字节，跳过")
                search_start = header_pos + cls.MAGIC_LENGTH
                continue
            if cls._validate_packet_structure(full_packet):
                packets.append(full_packet)
                search_start = packet_end
            else:
                cls._log_debug("无效数据包结构，跳过")
                search_start = header_pos + cls.MAGIC_LENGTH
        else:
            remaining_data = buffer[search_start:]

        # 记录处理结果
        if packets:
            cls._log_debug(
                f"找到 {len(packets)} 个数据包，剩余 {len(remaining_data)} 字节"
            )

        return packets, remaining_data

    @classmethod
    def _validate_packet_structure(cls, packet: bytes) -> bool:
        """验证数据包结构是否有效"""
        try:
            # 检查长度
            if len(packet) < cls.MAGIC_LENGTH * 2:
                cls._log_warning(f"数据包过短: {len(packet)}字节")
                return False

            # 检查头尾magic
            header = packet[: cls.MAGIC_LENGTH]
            footer = packet[-cls.MAGIC_LENGTH :]

            if header != cls.MAGIC:
                cls._log_warning("包头magic不匹配")
                return False

            if footer != cls.MAGIC:
                cls._log_warning("包尾magic不匹配")
                return False

            # 检查内容长度
            content = packet[cls.MAGIC_LENGTH : -cls.MAGIC_LENGTH]
            if len(content) < 1:
                cls._log_warning("数据包内容为空")
                return False

            # 检查opcode范围
            opcode = content[0]
            if opcode > 0xFF:  # opcode应该是0-255
                cls._log_warning(f"无效opcode: {opcode}")
                return False

            return True

        except Exception as e:
            cls._log_error(f"数据包结构验证错误: {e}")
            return False

    @classmethod
    def parse_packet(cls, packet: bytes) -> Optional[Dict[str, Any]]:
        """解析数据包（增强错误处理）"""
        try:
            # 基础验证
            if not cls._validate_packet_structure(packet):
                return None

            # 提取数据内容
            content = packet[cls.MAGIC_LENGTH : -cls.MAGIC_LENGTH]

            # 解析opcode
            opcode = content[0]

            # 数据段（opcode之后的所有数据）
            data_section = content[1:] if len(content) > 1 else b""

            return {
                "opcode": opcode,
                "data_section": data_section,
                "data_length": len(data_section),
                "raw_packet": packet,
                "packet_length": len(packet),
                "timestamp": datetime.now(),
            }

        except Exception as e:
            cls._log_error(f"数据包解析错误: {e}")
            return None

    @classmethod
    def create_packet(cls, opcode: int, data: bytes = b"") -> bytes:
        try:
            if not isinstance(opcode, int) or opcode < 0 or opcode > 255:
                raise ValueError("opcode必须是0-255之间的整数")

            if not isinstance(data, bytes):
                raise ValueError("data必须是bytes类型")

            if len(data) > 1024:
                raise ValueError("数据长度超过限制")

            return cls.MAGIC + bytes([opcode]) + data + cls.MAGIC

        except Exception as e:
            cls._log_error(f"创建数据包错误: {e}")
            raise

    @classmethod
    def _log_info(cls, message: str):
        logging.info(f"[DASProtocol] {message}")

    @classmethod
    def _log_debug(cls, message: str):
        logging.debug(f"[DASProtocol] {message}")

    @classmethod
    def _log_warning(cls, message: str):
        logging.warning(f"[DASProtocol] {message}")

    @classmethod
    def _log_error(cls, message: str):
        logging.error(f"[DASProtocol] {message}")


class DASController:
    def __init__(self):
        self.buffer = b""
        self.buffer_lock = threading.Lock()
        self.error_count = 0
        self.max_consecutive_errors = 10
        self.consecutive_errors = 0
        self.stats = {
            "total_packets": 0,
            "valid_packets": 0,
            "invalid_packets": 0,
            "recovered_packets": 0,
            "buffer_resets": 0,
        }

    def process_received_data(self, new_data: bytes):
        try:
            with self.buffer_lock:
                self.buffer += new_data

                # 检查缓冲区健康度
                if not self._check_buffer_health():
                    self._reset_buffer()
                    return

                # 查找完整数据包
                packets, remaining_data = DASProtocol.find_packet(self.buffer)

                # 更新缓冲区
                self.buffer = remaining_data

            # 处理找到的数据包
            for packet in packets:
                self._handle_packet_with_retry(packet)

            self._log_warning("find packets num: {}".format(len(packets)))

        except Exception as e:
            self._handle_processing_error(e)

    def _check_buffer_health(self) -> bool:
        # 检查缓冲区大小
        if len(self.buffer) > DASProtocol.MAX_BUFFER_SIZE:
            self._log_error(f"缓冲区过大: {len(self.buffer)}字节")
            return False
        return True

    def _reset_buffer(self):
        """重置缓冲区"""
        self._log_warning("重置缓冲区")
        self.buffer = b""
        self.consecutive_errors = 0
        self.stats["buffer_resets"] += 1

    def _handle_packet_with_retry(self, packet: bytes, max_retries: int = 3):
        """带重试的数据包处理"""
        for attempt in range(max_retries):
            try:
                parsed = DASProtocol.parse_packet(packet)
                if parsed:
                    self._handle_valid_packet(parsed)
                    return
                else:
                    self._handle_invalid_packet(packet, attempt)
            except Exception as e:
                self._log_error(f"数据包处理错误 (尝试 {attempt+1}): {e}")

        self.stats["invalid_packets"] += 1

    def _handle_valid_packet(self, parsed_packet: Dict):
        """处理有效数据包"""
        self.stats["valid_packets"] += 1
        self.stats["total_packets"] += 1

        print(
            f"[{parsed_packet['timestamp'].strftime('%H:%M:%S.%f')}] "
            f"有效数据包 - OPCODE: 0x{parsed_packet['opcode']:02X}, "
            f"数据长度: {parsed_packet['data_length']}"
        )

        # 根据opcode分发处理
        self._dispatch_by_opcode(parsed_packet["opcode"], parsed_packet["data_section"])

    def _handle_invalid_packet(self, packet: bytes, attempt: int):
        self._log_warning(f"无效数据包 (尝试 {attempt+1}): 长度={len(packet)}字节")

        # 记录无效包内容（用于调试）
        if attempt == 0:  # 只在第一次尝试时记录
            self._log_debug(f"无效包内容: {packet.hex()[:100]}...")

    def _handle_processing_error(self, error: Exception):
        """处理处理过程中的错误"""
        self.error_count += 1
        self.consecutive_errors += 1

        self._log_error(f"数据处理错误: {error}")

        # 如果错误过多，考虑重置
        if self.consecutive_errors >= self.max_consecutive_errors:
            self._log_error("错误过多，执行恢复操作")
            self._reset_buffer()

    def _dispatch_by_opcode(self, opcode: int, data: bytes):
        """根据opcode分发处理"""
        try:
            if opcode == 0x01:
                self._handle_sensor_data(data)
            elif opcode == 0x02:
                self._handle_config_data(data)
            elif opcode == 0x03:
                self._handle_status_data(data)
            else:
                self._log_warning(f"未知OPCODE: 0x{opcode:02X}")
        except Exception as e:
            self._log_error(f"OPCODE处理错误: {e}")

    def _handle_sensor_data(self, data: bytes):
        """处理传感器数据"""
        try:
            # 解析传感器数据
            if len(data) >= 4:
                # 示例：解析时间戳和数据值
                timestamp = int.from_bytes(data[:4], "little")
                sensor_value = data[4:] if len(data) > 4 else b""
                print(f"传感器数据 - 时间戳: {timestamp}, 值: {sensor_value.hex()}")
        except Exception as e:
            self._log_error(f"传感器数据处理错误: {e}")

    def _handle_config_data(self, data: bytes):
        print("处理配置数据")

    def _handle_status_data(self, data: bytes):
        print("处理状态数据")

    def get_statistics(self) -> Dict:
        return self.stats.copy()

    def _log_info(self, message: str):
        logging.info(f"[DASController] {message}")

    def _log_debug(self, message: str):
        logging.debug(f"[DASController] {message}")

    def _log_warning(self, message: str):
        logging.warning(f"[DASController] {message}")

    def _log_error(self, message: str):
        logging.error(f"[DASController] {message}")

