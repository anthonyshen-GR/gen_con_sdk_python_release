#!/usr/bin/env python3
"""
Camera - Pure Python implementation for camera capture
Removed ROS dependencies, using callbacks instead of ROS topics
"""

import cv2
import os
import time
import glob
import subprocess
import signal
import sys
import numpy as np
import threading
import re
from typing import List, Callable, Optional, Tuple


class CameraCapture:
    def __init__(
        self,
        serial_port: str = "",
        camera_count: int = 3,
        resolutions: List[Tuple[int, int]] = None,
        show_preview: bool = True,
        video_devices: List[str] = None,
        frame_callback: Optional[Callable] = None,
    ):
        """
        初始化摄像头采集
        
        Args:
            serial_port: USB串口设备路径（用于过滤视频设备）
            camera_count: 摄像头数量
            resolutions: 分辨率列表，格式为[(width, height), ...]
            show_preview: 是否显示预览窗口
            video_devices: 视频设备路径列表，格式为["/dev/video0", "/dev/video1", ...]
            frame_callback: 帧数据回调函数，格式为callback(camera_id, frame, timestamp)
        """
        self.serial_port = serial_port
        self.camera_count = camera_count
        self.resolutions = resolutions or [(1600, 1296)]
        self.show_preview = show_preview
        self.video_devices = video_devices or []
        self.frame_callback = frame_callback
        
        self.cameras = []
        self.running = True
        
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        self._init_cameras()

    def _signal_handler(self, signum, frame):
        """信号处理函数"""
        print(f"\n接收到终止信号({signum})，正在停止采集...")
        self.running = False

    def _get_physical_devices(self):
        """获取物理视频设备"""
        try:
            result = subprocess.run(['v4l2-ctl', '--list-devices'], 
                                 capture_output=True, text=True)
            devices = []
            current_dev = ""
            device_names = {}
            
            for line in result.stdout.split('\n'):
                if not line.strip():
                    continue
                if ':' in line and not line.startswith('/dev/'):
                    current_dev = line.split(':')[0].strip()
                elif line.startswith('/dev/video'):
                    dev_path = line.strip()
                    if os.path.exists(dev_path):
                        devices.append(dev_path)
                        device_names[dev_path] = current_dev
            
            print(f"检测到所有视频设备: {devices}")
            
            # 如果指定了视频设备，使用指定的设备
            if self.video_devices:
                filtered_devices = []
                for dev in self.video_devices:
                    if os.path.exists(dev):
                        filtered_devices.append(dev)
                if filtered_devices:
                    devices = filtered_devices
                    print(f"使用指定的视频设备: {devices}")
            
            # 注意：不在这里限制设备数量，让_init_cameras方法自己处理设备选择逻辑
            
            return sorted(list(set(devices))) if devices else sorted(glob.glob('/dev/video*'))
        except Exception as e:
            print(f"获取视频设备时出错: {e}")
            return sorted(glob.glob('/dev/video*'))

    def _try_reset_device(self, dev_path):
        """尝试重置设备"""
        try:
            udev_info = subprocess.run(
                ['udevadm', 'info', '-q', 'path', '-n', dev_path],
                capture_output=True, text=True
            ).stdout.strip()
            
            if udev_info:
                usb_path = f"/sys{udev_info}/../reset"
                if os.path.exists(usb_path):
                    with open(usb_path, 'w') as f:
                        f.write('1')
                    time.sleep(2)
                    return True
        except:
            pass
        return False

    def _init_camera(self, dev_path, cam_id):
        """初始化单个摄像头"""
        for attempt in range(3):
            try:
                if not os.path.exists(dev_path):
                    print(f"设备 {dev_path} 不存在")
                    continue

                if attempt > 0:
                    self._try_reset_device(dev_path)
                    os.system(f'sudo chmod 666 {dev_path}')
                    os.system(f'sudo fuser -k {dev_path} 2>/dev/null')

                cap = cv2.VideoCapture(dev_path, cv2.CAP_V4L2)
                if not cap.isOpened():
                    print('OpenCV无法打开设备')
                    return False

                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M','J','P','G'))
                
                # 尝试设置指定的分辨率
                success = False
                actual_width = 0
                actual_height = 0
                
                for res in self.resolutions:
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, res[0])
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, res[1])
                    actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    
                    if actual_width == res[0] and actual_height == res[1]:
                        print(f"摄像头{cam_id}成功设置为 {actual_width}x{actual_height}")
                        success = True
                        break
                    else:
                        print(f"摄像头{cam_id}无法设置为 {res[0]}x{res[1]}, 实际为 {actual_width}x{actual_height}")
                
                if not success:
                    print(f"摄像头{cam_id}无法设置为任何指定分辨率，使用默认分辨率 {actual_width}x{actual_height}")
                
                for _ in range(5):
                    cap.grab()
                    time.sleep(0.01)

                # 再次获取实际分辨率
                actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                
                window_name = f'Camera_{cam_id}_{actual_width}x{actual_height}'
                
                self.cameras.append({
                    'id': cam_id,
                    'cap': cap,
                    'dev': dev_path,
                    'frame_count': 0,
                    'width': actual_width,
                    'height': actual_height,
                    'window_name': window_name
                })
                return True

            except Exception as e:
                print(f"尝试#{attempt+1} 初始化 {dev_path} 失败: {str(e)}")
                if 'cap' in locals() and cap.isOpened():
                    cap.release()
                time.sleep(1)
        return False

    def _init_main_or_second_camera(self, dev_main, dev_sec, cam_id):
        """初始化单个摄像头（尝试main和sec两个设备）"""
        if dev_main and os.path.exists(dev_main):
            if self._init_camera(dev_main, cam_id):
                print(f"成功初始化摄像头 {dev_main} 为 camera_{cam_id}")
                return True
        elif dev_main:
            print(f"⚠️ 设备 {dev_main} 不存在，尝试备用设备")
        
        if dev_sec and os.path.exists(dev_sec):
            if self._init_camera(dev_sec, cam_id):
                print(f"成功初始化摄像头 {dev_sec} 为 camera_{cam_id}")
                return True
        
        print(f"⚠️ 无法初始化摄像头 {cam_id}（main: {dev_main}, sec: {dev_sec}）")
        return False

    def _find_configured_camera_devices(self):
        """
        查找已配置的摄像头设备（符号链接）
        查找格式：/dev/*_video_*_main 和 /dev/*_video_*_sec
        
        Returns:
            字典，键为摄像头编号(0,1,2)，值为(main_dev, sec_dev)元组
        """
        import glob
        
        # 查找所有匹配的符号链接
        main_devices = glob.glob('/dev/*_video_*_main')
        sec_devices = glob.glob('/dev/*_video_*_sec')
        
        # 提取摄像头编号并排序
        camera_configs = {}
        
        # 处理main设备
        for dev in main_devices:
            # 匹配 video_0_main, video_1_main, video_2_main 等
            match = re.search(r'video_(\d+)_main', dev)
            if match:
                cam_num = int(match.group(1))
                if cam_num not in camera_configs:
                    camera_configs[cam_num] = (dev, None)
                else:
                    camera_configs[cam_num] = (dev, camera_configs[cam_num][1])
        
        # 处理sec设备
        for dev in sec_devices:
            match = re.search(r'video_(\d+)_sec', dev)
            if match:
                cam_num = int(match.group(1))
                if cam_num not in camera_configs:
                    camera_configs[cam_num] = (None, dev)
                else:
                    camera_configs[cam_num] = (camera_configs[cam_num][0], dev)
        
        return camera_configs

    def _init_cameras(self):
        """初始化所有摄像头"""
        # 如果指定了视频设备，使用指定的设备配置
        # 假设video_devices是6个设备的列表：[video0_main, video0_sec, video1_main, video1_sec, video2_main, video2_sec]
        # 或者3个设备的列表（只指定main设备）
        if self.video_devices:
            if len(self.video_devices) >= 6:
                # 6个设备：每个摄像头有main和sec
                video_configs = [
                    (self.video_devices[0], self.video_devices[1]),  # cam0: main, sec
                    (self.video_devices[2], self.video_devices[3]),  # cam1: main, sec
                    (self.video_devices[4], self.video_devices[5]),  # cam2: main, sec
                ]
            elif len(self.video_devices) == 3:
                # 3个设备：只指定main设备
                video_configs = [
                    (self.video_devices[0], ''),  # cam0: main only
                    (self.video_devices[1], ''),  # cam1: main only
                    (self.video_devices[2], ''),  # cam2: main only
                ]
            else:
                print(f"⚠️ video_devices参数数量不正确（{len(self.video_devices)}），期望3或6个设备")
                video_configs = None
            
            if video_configs:
                # 使用指定的设备配置
                # 注意：根据launch文件，cam1和cam2的设备是交换的
                # cam_id=0: video_0_main, video_0_sec
                # cam_id=1: video_2_main, video_2_sec (交换了)
                # cam_id=2: video_1_main, video_1_sec (交换了)
                video_mapping = [
                    (video_configs[0][0], video_configs[0][1]),  # cam0: video_0
                    (video_configs[2][0], video_configs[2][1]),  # cam1: video_2 (交换)
                    (video_configs[1][0], video_configs[1][1]),  # cam2: video_1 (交换)
                ]
                
                for cam_id, (dev_main, dev_sec) in enumerate(video_mapping):
                    self._init_main_or_second_camera(dev_main, dev_sec, cam_id)
        else:
            # 查找已配置的摄像头设备（符号链接）
            camera_configs = self._find_configured_camera_devices()
            
            if not camera_configs:
                print("\n" + "=" * 60)
                print("❌ 错误：未找到已配置的摄像头设备")
                print("=" * 60)
                print("\n请按照以下步骤配置摄像头设备：")
                print("1. 参考 python/配置方法样例/README_CN.md 中的配置方法")
                print("2. 创建 udev 规则文件（如 99-usb-serial.rules）")
                print("3. 在规则文件中配置摄像头符号链接，格式如下：")
                print("   SYMLINK+=\"left_video_0_main\"  (中间相机主设备)")
                print("   SYMLINK+=\"left_video_0_sec\"   (中间相机副设备)")
                print("   SYMLINK+=\"left_video_1_main\"  (左侧相机主设备)")
                print("   SYMLINK+=\"left_video_1_sec\"   (左侧相机副设备)")
                print("   SYMLINK+=\"left_video_2_main\"  (右侧相机主设备)")
                print("   SYMLINK+=\"left_video_2_sec\"   (右侧相机副设备)")
                print("4. 将规则文件复制到 /etc/udev/rules.d/")
                print("5. 加载配置：")
                print("   sudo udevadm control --reload-rules")
                print("   sudo udevadm trigger")
                print("\n配置完成后，应该能在 /dev/ 目录下看到 *_video_*_main 和 *_video_*_sec 符号链接")
                print("例如: /dev/left_video_0_main, /dev/left_video_0_sec 等")
                print("=" * 60 + "\n")
                sys.exit(1)
            
            # 检查是否至少有三个摄像头（video_0, video_1, video_2）
            required_cams = [0, 1, 2]
            missing_cams = []
            for cam_num in required_cams:
                if cam_num not in camera_configs:
                    missing_cams.append(cam_num)
                elif camera_configs[cam_num][0] is None:  # 没有main设备
                    missing_cams.append(cam_num)
            
            if missing_cams:
                print(f"\n❌ 错误：缺少已配置的摄像头设备")
                print(f"缺少的摄像头编号: {missing_cams}")
                print("请确保已配置 video_0, video_1, video_2 三个摄像头的符号链接")
                print("参考 python/配置方法样例/README_CN.md 中的配置方法")
                sys.exit(1)
            
            # 使用已配置的设备，注意cam1和cam2是交换的
            # cam_id=0: video_0
            # cam_id=1: video_2 (交换)
            # cam_id=2: video_1 (交换)
            video_mapping = [
                (camera_configs[0][0], camera_configs[0][1]),  # cam0: video_0
                (camera_configs[2][0], camera_configs[2][1]),  # cam1: video_2 (交换)
                (camera_configs[1][0], camera_configs[1][1]),  # cam2: video_1 (交换)
            ]
            
            print(f"找到已配置的摄像头设备:")
            for cam_id, (dev_main, dev_sec) in enumerate(video_mapping):
                print(f"  Camera_{cam_id}: main={dev_main}, sec={dev_sec}")
            
            for cam_id, (dev_main, dev_sec) in enumerate(video_mapping):
                self._init_main_or_second_camera(dev_main, dev_sec, cam_id)

        if not self.cameras:
            print("\n❌ 错误：没有可用的摄像头")
            print("请执行以下诊断命令：")
            print("1. 检查设备连接: ls /dev/video*")
            print("2. 查看设备信息: v4l2-ctl --list-devices")
            print("3. 检查符号链接: ls -l /dev/*_video_*")
            print("4. 修复权限: sudo chmod 666 /dev/*_video_*")
            print("\n提示：必须按照 python/配置方法样例/README_CN.md 配置摄像头设备")
            sys.exit(1)
        
        print(f"\n✅ 成功初始化 {len(self.cameras)} 个摄像头")

    def _display_frames(self, frames_data):
        """显示摄像头画面"""
        for cam, frame in frames_data:
            if frame is not None:
                # 在画面上添加时间戳和帧计数信息
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                info_text = f"Camera_{cam['id']} | {timestamp} | Frames: {cam['frame_count']}"
                cv2.putText(frame, info_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 
                          0.7, (0, 255, 0), 2)
                
                # 显示画面
                cv2.imshow(cam['window_name'], frame)
        
        # 检查是否按下ESC键
        if cv2.waitKey(1) == 27:
            self.running = False

    def capture_frames_callback(self):
        """
        开始采集帧（已重命名，主要逻辑已移至 start_gripper.py 中的 capture_frames_callback）
        保留此方法以保持向后兼容性
        """
        print(f"\n开始持续采集 {len(self.cameras)} 个摄像头...")
        print("按下ESC键或Ctrl+C停止采集")
        
        # 创建预览窗口
        if self.show_preview:
            for cam in self.cameras:
                RESIZE_WIDTH = 640
                RESIZE_HEIGHT = 480
                cv2.namedWindow(cam['window_name'], cv2.WINDOW_NORMAL)
                cv2.resizeWindow(cam['window_name'], RESIZE_WIDTH, RESIZE_HEIGHT)
        
        frame_num = 0
        target_fps = 30
        frame_interval = 1.0 / target_fps
        
        try:
            while self.running:
                frames_data = []
                timestamp_ns = time.time_ns()
                start_time = time.time()
                
                # 读取所有摄像头的帧
                for cam in self.cameras:
                    ret, frame = cam['cap'].read()
                    if not ret:
                        frame = None
                    else:
                        # 调用回调函数
                        if self.frame_callback:
                            try:
                                self.frame_callback(cam['id'], frame, timestamp_ns)
                            except Exception as e:
                                print(f"回调函数错误: {e}")
                        cam['frame_count'] += 1
                    
                    frames_data.append((cam, frame))
                
                # 显示实时预览
                if self.show_preview:
                    self._display_frames(frames_data)
                
                frame_num += 1
                
                # 控制帧率
                elapsed = time.time() - start_time
                sleep_time = max(0, frame_interval - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)
                
        except Exception as e:
            print(f"采集过程中出错: {e}")
        finally:
            self._release_resources()
    
    def capture_frames(self):
        """
        开始采集帧（向后兼容方法，内部调用 capture_frames_callback）
        """
        self.capture_frames_callback()

    def _release_resources(self):
        """释放资源"""
        for cam in self.cameras:
            try:
                cam['cap'].release()
            except:
                pass
        
        # 关闭所有窗口
        if self.show_preview:
            for cam in self.cameras:
                try:
                    cv2.destroyWindow(cam['window_name'])
                except:
                    pass

    def stop(self):
        """停止采集"""
        self.running = False
        self._release_resources()

