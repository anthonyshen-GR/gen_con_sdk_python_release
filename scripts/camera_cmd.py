#!/usr/bin/env python3
"""
Camera Command Tool - Pure Python implementation
Replaces camera_cmd.sh for sending camera calibration commands
"""

import sys
import time
import os

# 支持直接运行脚本: python camera_cmd.py 或 python -m ...scripts.camera_cmd
if __name__ == "__main__" or not __package__:
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    _parent_dir = os.path.dirname(_script_dir)
    if _parent_dir not in sys.path:
        sys.path.insert(0, _parent_dir)
    from scripts.databus import DataBus, find_serial_port
    from scripts.pack import CmdPack
else:
    from .databus import DataBus, find_serial_port
    from .pack import CmdPack


def camera_calib_callback(camera_pack):
    """摄像头标定数据回调函数"""
    print("摄像头标定数据已接收")


def main():
    """主函数"""
    SIDE_CONFIG = {
        'single': {'serial_port': ''},   # 单设备模式：不指定默认串口，用环境变量或自动查找
        'left': {'serial_port': "/dev/ttyDeviceLeft"},
        'right': {'serial_port': "/dev/ttyDeviceRight"},
    }

    usage = """
用法:
  单设备模式（不指定 left/right 时默认为 single）:
    python -m gen_controller_python_sdk.camera_cmd {1234|camerarc|camerarl|camerarr|MCUID}
  双设备模式（指定左右）:
    python -m gen_controller_python_sdk.camera_cmd {left|right} {1234|camerarc|camerarl|camerarr|MCUID}
  
  可选环境变量: SERIAL_PORT=/dev/ttyUSB0 指定串口设备（覆盖 left/right 默认串口）
  
  参数说明:
    left/right - 可选，指定夹爪侧（不传则默认为 single 单设备模式）
    1234       - 标定完成确认
    camerarc   - 中间相机标定（生成cam0_sensor_{single|left|right}.yaml）
    camerarl   - 左侧相机标定（生成cam1_sensor_{single|left|right}.yaml）
    camerarr   - 右侧相机标定（生成cam2_sensor_{single|left|right}.yaml）
    MCUID      - 查询设备MCUID
    """
    
    if len(sys.argv) < 2:
        print(usage)
        sys.exit(1)
    
    # 不设置 left/right 时默认为 single 单设备模式
    if len(sys.argv) == 2:
        side = 'single'
        record_value = sys.argv[1]
    else:
        side = sys.argv[1].lower()
        if side not in SIDE_CONFIG:
            print(f"错误: 第一参数必须是 left 或 right，当前为 '{sys.argv[1]}'")
            print(usage)
            sys.exit(1)
        record_value = sys.argv[2]
    
    # 校验RECORD_VALUE
    valid_commands = ['1234', 'camerarc', 'camerarl', 'camerarr', 'MCUID']
    if record_value not in valid_commands:
        print(f"错误: 参数必须是 {valid_commands} 之一")
        print(usage)
        sys.exit(1)
    
    # 根据传入的命令参数决定生成的YAML文件名（含 left/right 侧别）
    yaml_filename = ""
    if record_value == "camerarc":
        yaml_filename = f"cam0_sensor_{side}.yaml"
    elif record_value == "camerarl":
        yaml_filename = f"cam1_sensor_{side}.yaml"
    elif record_value == "camerarr":
        yaml_filename = f"cam2_sensor_{side}.yaml"
    
    # 设置YAML文件名到环境变量，供MessagePack使用
    if yaml_filename:
        # 获取gen_controller_python_sdk目录的绝对路径（当前文件所在目录）
        script_dir = os.path.dirname(os.path.abspath(__file__))
        # YAML文件将保存到gen_controller_python_sdk/calib_result目录
        result_dir = os.path.join(script_dir, "calib_result")
        
        os.environ['CALIB_YAML_FILENAME'] = yaml_filename
        print(f"将生成YAML文件: {yaml_filename}")
        print(f"保存路径: {os.path.join(result_dir, yaml_filename)}")
    else:
        # 确保没有这个环境变量
        if 'CALIB_YAML_FILENAME' in os.environ:
            del os.environ['CALIB_YAML_FILENAME']
    
    # 串口选择：优先使用环境变量，否则根据 side (single/left/right) 使用对应默认串口
    serial_port = os.environ.get('SERIAL_PORT', '')
    if not serial_port:
        serial_port = SIDE_CONFIG[side]['serial_port']
    if not serial_port:
        serial_port = find_serial_port("ttyUSB")  # single 或未配置时：自动查找设备
    
    if not serial_port:
        print("❌ 未找到已配置的串口设备")
        sys.exit(1)
    
    print(f"使用设备侧: {side}")
    print(f"使用串口: {serial_port}")
    print(f"发送相机标定指令: {record_value}")
    
    # 建立总线并发送命令
    try:
        bus = DataBus(
            tty_port=serial_port,
            baudrate=921600,
            is_calib_cmd=True,
            camera_calib_callback=camera_calib_callback,
        )
        time.sleep(1.0)  # 预留设备初始化时间
        bus.add_cmd(CmdPack.pack_calib(record=record_value.encode("utf-8")))
        time.sleep(0.5)  # 预留设备处理时间
        
        # 等待响应
        print("等待设备响应...")
        time.sleep(2.0)
        
        bus.stop()
        
        # 特殊命令的处理
        if record_value == "1234":
            print("✅ Calibration OK !")
        elif record_value == "MCUID":
            print("✅ MCUID query executed")
        else:
            print(f"✅ 完成发送 {record_value} 指令")
            if yaml_filename:
                # 检查文件是否已生成在calib_result目录
                script_dir = os.path.dirname(os.path.abspath(__file__))
                result_dir = os.path.join(script_dir, "calib_result")
                yaml_path = os.path.join(result_dir, yaml_filename)
                if os.path.exists(yaml_path):
                    print(f"✅ YAML文件已生成: {yaml_path}")
                else:
                    print(f"⚠️ YAML文件未生成，请检查设备响应")
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
