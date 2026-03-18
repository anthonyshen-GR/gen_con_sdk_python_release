#!/usr/bin/env python3
"""
GripperSystem - 夹爪系统主类
用于启动和管理整个夹爪系统（串口通信和摄像头）
"""

import time
import signal
import threading
from typing import Optional, List, Callable
from .databus import DataBus, find_serial_port
from .camera import CameraCapture


class GripperSystem:
    """夹爪系统主类"""
    def __init__(
        self,
        serial_port: Optional[str] = None,
        camera_resolutions: str = "1600x1296",
        show_preview: bool = True,
        video_devices: Optional[List[str]] = None,
        tactile_callback: Optional[Callable] = None,
        encoder_callback: Optional[Callable] = None,
        capture_frames_callback: Optional[Callable] = None,
    ):
        """
        初始化夹爪系统
        
        Args:
            serial_port: 串口设备路径，如果为None则自动查找
            camera_resolutions: 摄像头分辨率，格式为"widthxheight"
            show_preview: 是否显示摄像头预览
            video_devices: 视频设备列表，格式为["/dev/video0", "/dev/video1", "/dev/video2"]
            tactile_callback: 触觉数据回调函数（可选）
            encoder_callback: 编码器数据回调函数（可选）
            capture_frames_callback: 摄像头帧采集回调函数（可选），如果不指定则使用camera.capture_frames_callback()
        """
        self.running = True
        self.serial_port = serial_port
        self.camera_resolutions = camera_resolutions
        self.show_preview = show_preview
        self.video_devices = video_devices
        self.tactile_callback = tactile_callback
        self.encoder_callback = encoder_callback
        self.capture_frames_callback = capture_frames_callback
        
        # 解析分辨率
        self.resolutions = []
        for res_str in camera_resolutions.split(','):
            try:
                width, height = map(int, res_str.strip().split('x'))
                self.resolutions.append((width, height))
            except:
                pass
        
        if not self.resolutions:
            self.resolutions = [(1600, 1296)]
        
        # 初始化组件
        self.databus = None
        self.camera = None
        
        # 注册信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """信号处理函数"""
        if not self.running:
            # 如果已经在停止过程中，直接退出
            import sys
            sys.exit(0)
        print(f"\n接收到终止信号({signum})，正在停止系统...")
        self.running = False
    
    def start(self):
        """启动系统"""
        print("=" * 60)
        print("启动夹爪系统...")
        print("=" * 60)
        
        # 1. 先查找串口（用于摄像头初始化，但暂不初始化DataBus）
        if not self.serial_port:
            self.serial_port = find_serial_port("ttyUSB")
            if not self.serial_port:
                print("❌ 未找到可用的串口设备")
                return False
        
        print(f"使用串口: {self.serial_port}")
        
        # 2. 启动摄像头（优先初始化）
        print("\n[1/2] 初始化摄像头...")
        try:
            self.camera = CameraCapture(
                serial_port=self.serial_port,
                camera_count=3,
                resolutions=self.resolutions,
                show_preview=self.show_preview,
                video_devices=self.video_devices,
            )
            print("✅ 摄像头初始化成功")
            # 重新注册信号处理器，确保GripperSystem的处理器优先级更高
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
        except Exception as e:
            print(f"❌ 摄像头初始化失败: {e}")
            self.stop()
            return False
        
        # 给设备一些初始化时间
        time.sleep(1.0)
        
        # 3. 启动DataBus（串口通信）
        print("\n[2/2] 初始化串口通信...")
        try:
            self.databus = DataBus(
                tty_port=self.serial_port,
                baudrate=921600,
                encoder_freq=50,  # 50Hz编码器查询
                # tactile_freq=50,  # 50Hz触觉传感器查询
                tactile_callback=self.tactile_callback,
                encoder_callback=self.encoder_callback,
            )
            print("✅ 串口通信初始化成功")
        except Exception as e:
            print(f"❌ 串口通信初始化失败: {e}")
            self.stop()
            return False
        
        print("\n" + "=" * 60)
        print("✅ 系统启动完成！")
        print("=" * 60)
        print("\n功能说明:")
        print("  - 摄像头预览窗口已打开（3个窗口）")
        print("  - 夹爪控制: 使用GripperController类控制夹爪开合")
        print("  - 按ESC键或Ctrl+C停止系统")
        print("=" * 60)
        
        # 启动摄像头采集（阻塞）
        try:
            # 如果提供了外部回调函数，使用它；否则使用camera内部的方法
            if self.capture_frames_callback:
                camera_thread = threading.Thread(target=self.capture_frames_callback, args=(self.camera,))
            else:
                camera_thread = threading.Thread(target=self.camera.capture_frames_callback)
            camera_thread.daemon = True
            camera_thread.start()
            
            # 主循环 - 使用较短的睡眠时间以便快速响应信号
            while self.running:
                try:
                    time.sleep(0.1)
                except KeyboardInterrupt:
                    # 如果sleep被中断，立即退出循环
                    self.running = False
                    break
            
        except KeyboardInterrupt:
            print("\n用户中断")
        except Exception as e:
            print(f"\n系统错误: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.stop()
        
        return True
    
    def stop(self):
        """停止系统"""
        print("\n正在停止系统...")
        
        if self.camera:
            self.camera.stop()
        
        if self.databus:
            self.databus.stop()
        
        print("✅ 系统已停止")
    
    def set_gripper_distance(self, distance: float):
        """
        设置夹爪开合距离
        
        Args:
            distance: 目标距离，范围[0.0, 0.103]米（最大10cm）
        """
        if self.databus:
            self.databus.set_target_distance(distance)
        else:
            print("⚠️ DataBus未初始化")
