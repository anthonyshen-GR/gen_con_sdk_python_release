#!/usr/bin/env python3
"""
DataBus - Pure Python implementation for gripper communication
Removed ROS dependencies, using callbacks instead of ROS topics
"""

import serial
import serial.tools.list_ports
import threading
import time
import logging
import queue
import traceback
import struct
import os
import subprocess
from typing import Callable, Optional
from .pack import CmdPack, MessagePack, Opcode, RecordType
from .das_protocol import DASProtocol


# 默认回调函数已移至用户脚本中（gripper_controller.py, start_gripper.py, camera_cmd.py）
# 这样即使 databus.py 被加密，用户仍然可以访问和修改回调函数


class DataBus:
    def __init__(
        self,
        tty_port="/dev/ttyUSB0",
        baudrate=921600,
        timeout=0.5,
        is_calib_cmd=False,
        encoder_freq: float = None,
        tactile_freq: float = None,
        tactile_callback: Optional[Callable] = None,
        encoder_callback: Optional[Callable] = None,
        camera_calib_callback: Optional[Callable] = None,
    ):
        """
        初始化DataBus
        
        Args:
            tty_port: 串口设备路径
            baudrate: 波特率
            timeout: 超时时间
            is_calib_cmd: 是否为标定命令模式
            encoder_freq: 编码器查询频率（Hz）
            tactile_freq: 触觉传感器查询频率（Hz）
            tactile_callback: 触觉数据回调函数
            encoder_callback: 编码器数据回调函数
            camera_calib_callback: 摄像头标定数据回调函数
        """
        self.tty_port = tty_port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None
        self.is_running = False

        self._open_serial_success = False
        self.protocol: DASProtocol = DASProtocol()
        self.data_buffer: bytes = b""
        self.data_buffer_lock = threading.Lock()
        self.serial_lock = threading.Lock()

        self.cmd_queue = queue.Queue(1000)

        self.read_thread: threading.Thread = None
        self.parse_thread: threading.Thread = None
        self.send_thread: threading.Thread = None

        self.encoder_freq = encoder_freq
        self.tactile_freq = tactile_freq
        self.encoder_thread: threading.Thread = None
        self.tactile_thread: threading.Thread = None
        
        self.gripper_dis = 0.0
        self.angle_lock = threading.Lock()
        self.is_calib_cmd = is_calib_cmd
        
        # 设置回调函数（如果未提供则为None，调用时会检查）
        self.tactile_callback = tactile_callback
        self.encoder_callback = encoder_callback
        self.camera_calib_callback = camera_calib_callback

        self._open_serial()
        if not self._open_serial_success:
            raise RuntimeError(f"无法打开串口: {tty_port}")
        
        self.is_running = True
        self._start_reading()
        self._start_parsing()
        self._start_sending()
        
        # 启动循环线程
        if self.encoder_freq:
            self._start_encoder_loop()
        if self.tactile_freq:
            self._start_tactile_loop()

    def set_target_distance(self, distance: float):
        """
        设置目标距离（夹爪开合度）
        
        Args:
            distance: 目标距离，范围[0.0, 0.103]米（最大10cm）
        """
        if distance < 0.0 or distance > 0.103:
            raise ValueError(f"距离必须在[0.0, 0.103]范围内，当前值: {distance}")
        
        with self.angle_lock:
            self.gripper_dis = distance
        # print(f"设置目标距离: {distance} m")

    def get_target_distance(self) -> float:
        """获取当前目标距离"""
        with self.angle_lock:
            return self.gripper_dis

    def drive_motor(self, angle_dgree: float):
        """驱动电机"""
        self.add_cmd(
            CmdPack.pack(
                opcode=Opcode.WriteDrive,
                record_type=RecordType.Drive,
                record=struct.pack(">f", angle_dgree),
            )
        )

    def disable_motor(self):
        """禁用电机"""
        self.add_cmd(
            CmdPack.pack(
                opcode=Opcode.DisableDrive,
                record_type=RecordType.Drive,
            )
        )
    
    def calib_encoder(self):
        """标定编码器"""
        self.add_cmd(
            CmdPack.pack(
                opcode=Opcode.CalibEncoder,
                record_type=RecordType.Drive,
            )
        )

    def send_camera_calib_cmd(self, camera_cmd: str):
        """发送摄像头标定命令"""
        try:
            self.is_calib_cmd = True
            cmd = CmdPack.pack_calib(
                record=camera_cmd.encode('utf-8')
            )
            success = self.add_cmd(cmd)
            if success:
                print(f"发送摄像头标定命令: {camera_cmd}")
            else:
                print(f"发送摄像头标定命令失败: {camera_cmd}")
            return success
        except Exception as e:
            print(f"发送摄像头标定命令时出错: {e}")
            return False

    def add_cmd(self, cmd: CmdPack) -> bool:
        """添加命令到队列"""
        try:
            self.cmd_queue.put(cmd, block=True, timeout=1)
            return True
        except queue.Full:
            print("命令队列已满，添加失败")
            return False

    def is_opened(self):
        """检查串口是否已打开"""
        return self._open_serial_success

    def register_tactile_callback(self, callback: Callable):
        """注册触觉数据回调函数"""
        self.tactile_callback = callback

    def register_encoder_callback(self, callback: Callable):
        """注册编码器数据回调函数"""
        self.encoder_callback = callback

    def register_camera_calib_callback(self, callback: Callable):
        """注册摄像头标定数据回调函数"""
        self.camera_calib_callback = callback

    def _open_serial(self):
        """打开串口"""
        try:
            self.ser = serial.Serial(
                port=self.tty_port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS,
            )

            if self.ser.is_open:
                print(f"打开串口成功: {self.tty_port}, 波特率: {self.baudrate}")
                self._open_serial_success = True
            else:
                print(f"打开串口失败: {self.tty_port}")
                self._open_serial_success = False
        except Exception as e:
            print(f"打开串口时出错: {e}")
            self._open_serial_success = False

    def _start_reading(self):
        """启动读取线程"""
        self.read_thread = threading.Thread(target=self._reading_loop)
        self.read_thread.daemon = True
        self.read_thread.start()
        print("读取线程已启动")
        return True

    def _start_parsing(self):
        """启动解析线程"""
        self.parse_thread = threading.Thread(target=self._parsing_loop)
        self.parse_thread.daemon = True
        self.parse_thread.start()
        print("解析线程已启动")
        return True

    def _start_encoder_loop(self):
        """启动编码器循环线程"""
        self.encoder_thread = threading.Thread(target=self._send_encoder_loop)
        self.encoder_thread.daemon = True
        self.encoder_thread.start()
        print("编码器循环线程已启动")
        return True

    def _start_tactile_loop(self):
        """启动触觉循环线程"""
        self.tactile_thread = threading.Thread(target=self._send_tactile_loop)
        self.tactile_thread.daemon = True
        self.tactile_thread.start()
        print("触觉循环线程已启动")
        return True

    def _start_sending(self):
        """启动发送线程"""
        self.send_thread = threading.Thread(target=self._sending_loop)
        self.send_thread.daemon = True
        self.send_thread.start()
        print("发送线程已启动")
        return True

    def _sending_loop(self):
        """发送线程主循环"""
        while self.is_running:
            try:
                cmd: CmdPack = self.cmd_queue.get(block=True, timeout=0.1)
                with self.serial_lock:
                    if self.ser and self.ser.is_open:
                        self.ser.write(cmd.data)
                        self.ser.flush()
                
            except queue.Empty:
                continue
            except Exception as e:
                print(f"发送错误: {e}")
                time.sleep(0.01)

    def _reading_loop(self):
        """读取线程主循环"""
        while self.is_running:
            try:
                with self.serial_lock:
                    if self.ser and self.ser.is_open:
                        n = self.ser.inWaiting()
                        if n:
                            # 读取所有可用数据，但限制单次读取大小避免阻塞
                            # 921600波特率下，单次读取不超过16KB
                            read_size = min(n, 16384)
                            data = self.ser.read(read_size)
                            if data:
                                with self.data_buffer_lock:
                                    self.data_buffer = self.data_buffer + data
                                # 如果还有数据未读完，继续读取，不立即休眠
                                if n > read_size:
                                    continue

            except Exception as e:
                print(f"读取循环错误: {e}")
                time.sleep(0.1)

            time.sleep(0.001)  # 适当休眠，避免CPU占用过高

    def _parsing_loop(self):
        """解析线程主循环"""
        while self.is_running:
            packets_to_process = []
            
            # 快速获取数据包列表，减少锁持有时间
            with self.data_buffer_lock:
                if len(self.data_buffer) > 0:
                    packets, remain = DASProtocol.find_packet(self.data_buffer)
                    self.data_buffer = remain
                    packets_to_process = packets.copy()  # 复制列表以便在锁外处理
                    
            # 在锁外处理数据包，避免阻塞读取线程
            for packet in packets_to_process:
                try:
                    if self.is_calib_cmd:
                        camera_pack = MessagePack.unpack_camera_calib(packet)
                        
                        if camera_pack:
                            if self.camera_calib_callback:
                                self.camera_calib_callback(camera_pack)
                            self.is_calib_cmd = False
                    else:
                        pack = MessagePack.unpack(packet)
                        if not pack:
                            # unpack返回None表示数据不完整，这是正常的，不需要记录错误
                            # 数据包会被保留在缓冲区中，等待更多数据到达
                            continue

                        # 数据包解析成功，处理其中的记录
                        for record in pack.records_:
                            try:
                                if record.record_type == RecordType.Tactile:
                                    if self.tactile_callback:
                                        self.tactile_callback(record.record_data)
                                elif record.record_type == RecordType.Encoder:
                                    if self.encoder_callback:
                                        self.encoder_callback(record.record_data)
                                elif record.record_type == RecordType.Echo:
                                    # Echo 类型数据不再处理
                                    pass
                                else:
                                    logging.error(
                                        "record type:{} invalid !".format(record.record_type)
                                    )
                            except Exception as e:
                                logging.error(f"回调函数执行错误: {e}")
                                
                except Exception as e:
                    logging.error(f"数据包处理错误: {e}")

            # 根据是否有数据包调整休眠时间
            if packets_to_process:
                time.sleep(0.001)  # 有数据时快速处理
            else:
                time.sleep(0.005)  # 无数据时稍长休眠，但不要太长

    def _send_encoder_loop(self):
        """编码器循环线程"""
        if not self.encoder_freq:
            return
            
        interval = 1.0 / self.encoder_freq
        print(f"编码器循环启动，频率: {self.encoder_freq}Hz, 间隔: {interval:.3f}s")
        
        while self.is_running:
            start_time = time.time()
            
            # 下发距离指令到电机
            with self.angle_lock:
                dis_target = self.gripper_dis
            
            self.add_cmd(
                CmdPack.pack(
                    opcode=Opcode.ReadBatch, 
                    record_type=RecordType.Encoder, 
                    record=struct.pack(">f", dis_target)
                ),
            )
            
            # 精确控制间隔时间
            elapsed = time.time() - start_time
            sleep_time = max(0, interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

        print("退出编码器循环线程")

    def _send_tactile_loop(self):
        """触觉循环线程"""
        if not self.tactile_freq:
            return
            
        interval = 1.0 / self.tactile_freq
        print(f"触觉循环启动，频率: {self.tactile_freq}Hz, 间隔: {interval:.3f}s")
        
        while self.is_running:
            start_time = time.time()
            self.add_cmd(
                CmdPack.pack(opcode=Opcode.ReadSingle, record_type=RecordType.Tactile, record=struct.pack(">f", 0.0))
            )
            
            # 精确控制间隔时间
            elapsed = time.time() - start_time
            sleep_time = max(0, interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

        print("退出触觉循环线程")

    def stop(self):
        """停止所有线程"""
        print("正在停止所有线程...")
        self.is_running = False
        
        # 等待所有线程结束
        threads_to_join = []
        if self.read_thread and self.read_thread.is_alive():
            threads_to_join.append(self.read_thread)
        if self.send_thread and self.send_thread.is_alive():
            threads_to_join.append(self.send_thread)
        if self.parse_thread and self.parse_thread.is_alive():
            threads_to_join.append(self.parse_thread)
        if self.encoder_thread and self.encoder_thread.is_alive():
            threads_to_join.append(self.encoder_thread)
        if self.tactile_thread and self.tactile_thread.is_alive():
            threads_to_join.append(self.tactile_thread)
        
        for thread in threads_to_join:
            thread.join(timeout=2)
        
        if self.ser and self.ser.is_open:
            self.ser.close()

    def get_serial_info(self):
        """获取串口信息"""
        if self.ser and self.ser.is_open:
            info = {
                "tty_port": self.tty_port,
                "baudrate": self.ser.baudrate,
                "bytesize": self.ser.bytesize,
                "parity": self.ser.parity,
                "stopbits": self.ser.stopbits,
                "timeout": self.ser.timeout,
                "in_waiting": self.ser.in_waiting,
            }
            return info
        return None


def check_and_fix_permission(port):
    """检查并修复串口设备权限"""
    if not os.path.exists(port):
        return False
    
    # 检查当前用户是否有读写权限
    if os.access(port, os.R_OK | os.W_OK):
        return True
    
    print(f"尝试修复 {port} 的权限...")
    try:
        # 尝试修改权限
        subprocess.run(['sudo', 'chmod', '666', port], check=True)
        print(f"权限修复成功: {port}")
        return True
    except subprocess.CalledProcessError:
        print(f"权限修复失败，请手动执行: sudo chmod 666 {port}")
        return False


def find_configured_serial_port():
    """
    查找已配置的USB串口设备（符号链接）
    只查找 /dev/ttyDevice* 格式的符号链接
    
    Returns:
        串口设备路径，如果未找到则返回None
    """
    # 查找所有 /dev/ttyDevice* 设备
    import glob
    configured_ports = glob.glob('/dev/ttyDevice*')
    
    if not configured_ports:
        return None
    
    # 返回第一个存在的有权限的设备
    for port in sorted(configured_ports):
        if os.path.exists(port) and check_and_fix_permission(port):
            return port
    
    # 如果都有权限问题，返回第一个（让用户手动处理）
    return sorted(configured_ports)[0] if configured_ports else None


def find_serial_port(pattern="ttyUSB", max_retries=3, retry_interval=2):
    """
    查找已配置的USB串口设备（符号链接）
    只查找 /dev/ttyDevice* 格式的符号链接，不再使用未配置的ttyUSB设备
    
    Args:
        pattern: 已废弃，保留仅为兼容性
        max_retries: 已废弃，保留仅为兼容性
        retry_interval: 已废弃，保留仅为兼容性
    
    Returns:
        串口设备路径，如果未找到则返回None并显示错误提示
    """
    # 只查找已配置的符号链接设备
    configured_port = find_configured_serial_port()
    
    if configured_port:
        print(f"使用已配置的串口设备: {configured_port}")
        return configured_port
    
    # 未找到已配置的设备，显示错误提示
    print("\n" + "=" * 60)
    print("❌ 错误：未找到已配置的USB串口设备")
    print("=" * 60)
    print("\n请按照以下步骤配置USB设备：")
    print("1. 参考 python/配置方法样例/README_CN.md 中的配置方法")
    print("2. 创建 udev 规则文件（如 99-usb-serial.rules）")
    print("3. 将规则文件复制到 /etc/udev/rules.d/")
    print("4. 加载配置：")
    print("   sudo udevadm control --reload-rules")
    print("   sudo udevadm trigger")
    print("\n配置完成后，应该能在 /dev/ 目录下看到 ttyDevice* 符号链接")
    print("例如: /dev/ttyDeviceLeft 或其他自定义名称")
    print("=" * 60 + "\n")
    return None

