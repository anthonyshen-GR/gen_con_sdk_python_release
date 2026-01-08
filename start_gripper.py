#!/usr/bin/env python3
"""启动脚本 - 启动夹爪设备和摄像头"""

import sys
import os
import argparse
import struct
import time
import cv2
import math
import threading
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_controller_sdk_python import GripperSystem


def capture_frames_callback(camera):
    """摄像头帧采集回调函数"""
    if camera.show_preview:
        for cam in camera.cameras:
            cv2.namedWindow(cam['window_name'], cv2.WINDOW_NORMAL)
            cv2.resizeWindow(cam['window_name'], 640, 480)
    
    target_fps = 30
    frame_interval = 1.0 / target_fps
    
    try:
        while camera.running:
            start_time = time.time()
            timestamp_ns = time.time_ns()
            frames_data = []
            
            for cam in camera.cameras:
                ret, frame = cam['cap'].read()
                if ret and camera.frame_callback:
                    try:
                        camera.frame_callback(cam['id'], frame, timestamp_ns)
                    except Exception as e:
                        print(f"回调函数错误: {e}")
                    cam['frame_count'] += 1
                frames_data.append((cam, frame if ret else None))
            
            if camera.show_preview:
                _display_frames(camera, frames_data)
            
            elapsed = time.time() - start_time
            sleep_time = max(0, frame_interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)
    except Exception as e:
        print(f"采集过程中出错: {e}")
    finally:
        camera._release_resources()


def _display_frames(camera, frames_data):
    """显示摄像头画面"""
    for cam, frame in frames_data:
        if frame is not None:
            cv2.imshow(cam['window_name'], frame)
    if cv2.waitKey(1) == 27:
        camera.running = False


def tactile_callback(record_data: bytes):
    """触觉数据回调函数"""
    if len(record_data) != 448:
        return
    try:
        raw_left_224 = [struct.unpack("B", record_data[i:i+1])[0] for i in range(0, 224)]
        raw_right_224 = [struct.unpack("B", record_data[i:i+1])[0] for i in range(224, 448)]
        print(f"tactile: left{len(raw_left_224)}, right{len(raw_right_224)}")
    except Exception as e:
        print(f"处理触觉数据错误: {e}")


def encoder_callback(record_data: bytes):
    """编码器数据回调函数"""
    try:
        encoder_value = struct.unpack(">f", record_data)[0]
        print(f"gripper distance: {encoder_value:.3f} m")
    except Exception as e:
        print(f"处理编码器数据错误: {e}")


class SineWaveController:
    """正弦波控制类"""
    
    def __init__(self, system: GripperSystem, amplitude: float = 0.05, 
                 center: float = 0.05, frequency: float = 0.5, duration: float = 1000):
        self.system = system
        self.amplitude = amplitude
        self.center = center
        self.frequency = frequency
        self.duration = duration
        self.running = False
        self.control_thread = None
        self.start_time = 0
        self.control_interval = 1.0 / 50.0
        
    def start(self):
        """开始正弦波控制"""
        if self.running:
            return
        if self.amplitude <= 0 or self.center - self.amplitude < 0 or self.center + self.amplitude > 0.103:
            print("❌ 正弦波参数超出范围")
            return
        
        self.running = True
        self.start_time = time.time()
        self.control_thread = threading.Thread(target=self._control_loop, daemon=True)
        self.control_thread.start()
        print(f"🚀 开始正弦波控制: 中心={self.center:.3f}m, 振幅=±{self.amplitude:.3f}m, 频率={self.frequency:.2f}Hz")
    
    def stop(self):
        """停止正弦波控制"""
        if not self.running:
            return
        self.running = False
        if self.control_thread:
            self.control_thread.join(timeout=1.0)
    
    def _control_loop(self):
        """控制循环"""
        try:
            while self.running:
                cycle_start = time.time()
                current_time = time.time() - self.start_time
                
                if self.duration > 0 and current_time >= self.duration:
                    self.running = False
                    break
                
                value = self.center + self.amplitude * math.sin(2 * math.pi * self.frequency * current_time)
                value = max(0.0, min(0.103, value))
                
                if self.system.databus:
                    self.system.databus.set_target_distance(value)
                
                elapsed = time.time() - cycle_start
                sleep_time = max(0, self.control_interval - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)
        except Exception as e:
            print(f"❌ 正弦波控制错误: {e}")
            self.running = False


class GripperController:
    """夹爪控制器，管理不同控制模式"""
    
    def __init__(self, system: GripperSystem):
        self.system = system
        self.sine_wave_controller: Optional[SineWaveController] = None
        
    def set_fixed_distance(self, distance: float):
        """设置固定夹爪距离"""
        if distance < 0.0 or distance > 0.103:
            print(f"⚠️ 警告: 距离值 {distance} 超出范围 [0.0, 0.103]，已忽略")
            return
        
        if self.sine_wave_controller and self.sine_wave_controller.running:
            self.sine_wave_controller.stop()
        
        try:
            self.system.set_gripper_distance(distance)
            print(f"✅ 设置夹爪固定距离: {distance} m ({distance*100:.1f} cm)")
        except Exception as e:
            print(f"❌ 设置夹爪距离失败: {e}")
    
    def start_sine_wave(self, amplitude: float = 0.05, center: float = 0.05, 
                        frequency: float = 0.5, duration: float = 60.0):
        """开始正弦波控制"""
        if self.sine_wave_controller and self.sine_wave_controller.running:
            self.sine_wave_controller.stop()
        
        self.sine_wave_controller = SineWaveController(
            system=self.system, amplitude=amplitude, center=center,
            frequency=frequency, duration=duration
        )
        self.sine_wave_controller.start()
    
    def stop_sine_wave(self):
        """停止正弦波控制"""
        if self.sine_wave_controller:
            self.sine_wave_controller.stop()
    
    def is_sine_wave_running(self) -> bool:
        """检查正弦波控制是否在运行"""
        return self.sine_wave_controller.running if self.sine_wave_controller else False


def main():
    """主函数"""
    SIDE_CONFIG = {
        'left': {
            'serial_port': "/dev/ttyDeviceLeft",
            'video_devices': [
                "/dev/left_video_0_main", "/dev/left_video_0_sec",
                "/dev/left_video_1_main", "/dev/left_video_1_sec",
                "/dev/left_video_2_main", "/dev/left_video_2_sec"
            ]
        },
        'right': {
            'serial_port': "/dev/ttyDeviceRight",
            'video_devices': [
                "/dev/right_video_0_main", "/dev/right_video_0_sec",
                "/dev/right_video_1_main", "/dev/right_video_1_sec",
                "/dev/right_video_2_main", "/dev/right_video_2_sec"
            ]
        }
    }
    
    parser = argparse.ArgumentParser(description="启动夹爪系统（支持正弦波控制）")
    parser.add_argument("side", type=str, choices=['left', 'right'],
                       help="指定夹爪侧（left 或 right）")
    parser.add_argument("--camera-resolutions", type=str, default="1600x1296",
                       help="摄像头分辨率，格式为'widthxheight'")
    parser.add_argument("--no-preview", action="store_true",
                       help="不显示摄像头预览窗口")
    
    control_group = parser.add_mutually_exclusive_group()
    control_group.add_argument("--distance", type=float, default=None,
                              help="设置固定夹爪距离（米），范围[0.0, 0.103]")
    control_group.add_argument("--sine-wave", action="store_true",
                              help="启用正弦波控制模式")
    
    parser.add_argument("--amplitude", type=float, default=0.025,
                       help="正弦波振幅（米），默认0.025")
    parser.add_argument("--center", type=float, default=0.05,
                       help="正弦波中心位置（米），默认0.05")
    parser.add_argument("--frequency", type=float, default=0.5,
                       help="正弦波频率（Hz），默认0.5")
    parser.add_argument("--duration", type=float, default=10.0,
                       help="正弦波持续时间（秒），0表示无限，默认10.0")
    
    args = parser.parse_args()
    config = SIDE_CONFIG[args.side]
    
    system = GripperSystem(
        serial_port=config['serial_port'],
        camera_resolutions=args.camera_resolutions,
        show_preview=not args.no_preview,
        video_devices=config['video_devices'],
        tactile_callback=tactile_callback,
        encoder_callback=encoder_callback,
        capture_frames_callback=capture_frames_callback,
    )
    
    controller = GripperController(system)
    
    def setup_control_mode():
        """在系统初始化完成后设置控制模式"""
        max_wait_time = 10.0
        wait_interval = 0.1
        elapsed_time = 0.0
        
        while elapsed_time < max_wait_time:
            if system.databus is not None:
                time.sleep(0.5)
                if args.sine_wave:
                    controller.start_sine_wave(
                        amplitude=args.amplitude, center=args.center,
                        frequency=args.frequency, duration=args.duration
                    )
                elif args.distance is not None:
                    controller.set_fixed_distance(args.distance)
                else:
                    controller.set_fixed_distance(0.05)
                return
            time.sleep(wait_interval)
            elapsed_time += wait_interval
        print("⚠️ 警告: 系统初始化超时，未能设置控制模式")
    
    threading.Thread(target=setup_control_mode, daemon=True).start()
    
    try:
        system.start()
    except KeyboardInterrupt:
        print("\n用户中断")
    finally:
        if controller.is_sine_wave_running():
            controller.stop_sine_wave()
        system.stop()


if __name__ == "__main__":
    main()