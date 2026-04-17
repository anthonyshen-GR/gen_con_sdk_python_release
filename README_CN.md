# genrobot_controller_sdk_python
## 环境部署
```
环境按requirements.txt配置
USB接口需3.0
```

## 配置USB接口

### 单爪USB口配置
最终配置形式如图,配置完后该USB口可以识别任意Gen Controller，后续无需再次配置，该文件模板存放在
```
config/99-usb-serial.rules
```
![image/image_1.png](image/image_1.png)  

用户需修改地方为:  
![image/image_2.png](image/image_2.png)  

参数1处修改方法如下，
执行：

```
cd /dev && ls | grep ttyUSB
udevadm info -a -n /dev/ttyUSB* | grep -E "KERNELS|DRIVERS"
```

将输出中的第二个KERNELS数值配置到1处:  
![image/image_3.png](image/image_3.png)

参数2处修改方法如下，执行：
```
v4l2-ctl --list-devices
```
输出  
![image/image_4.png](image/image_4.png)

然后针对该USB的第一个相机执行：
```
udevadm info -a -n /dev/video* | grep -E "KERNELS|SUBSYSTEMS"
```
将输出的第一个KERNELS数值配置为到2处  
![image/image_5.png](image/image_5.png)  
然后将模板文件copy至下列地址处
```
sudo cp config/99-usb-serial.rules /etc/udev/rules.d/
```
然后加载配置
```
sudo udevadm control --reload-rules
sudo udevadm trigger
```

### 双爪USB口配置
最终配置形式如图所示  
![image/image_6.png](image/image_6.png)

需修改地方  
![image/image_7.png](image/image_7.png)

首先插入左夹爪，按照单夹爪的配置方法进行配置；然后拔下左夹爪，插入右夹爪，再次按照单夹爪的配置方法进行配置；最后加载配置。

### 多爪USB口配置
再次同样添加配置到99-usb-serial.rules中。

## SDK运行
执行start_gripper.py  demo文件

### 单爪启动demo

```
cd gen_con_sdk_python_release

python3 start_gripper.py left   # 当前配置夹爪固定打开5cm

python3 start_gripper.py left --distance 0.08  # 夹爪固定打开8cm，输入距离区间为[0.0, 0.103],即最大可开10cm

python3 start_gripper.py left --sine-wave  # 夹爪持续开合10s

相机帧率（V4的Controller需要将帧率修改为60才能得到30fps的的图像数据）
python start_gripper.py left --camera-fps 60

```

启动后会弹出三个图像窗口:
```
/camera_0   # 中间相机
/camera_1   # 左侧相机
/camera_2   # 右侧相机

```
打印数据有：
```
tactile数据
gripper distance数据
```

### 双爪启动demo
```
cd gen_controller_sdk_python
启动
python3 start_gripper.py left
另一终端启动
python3 start_gripper.py right
触觉数据读取
python start_gripper.py right --print-tactile-info
相机帧率（V4的Controller需要将帧率修改为60才能得到30fps的的图像数据）
python start_gripper.py left --camera-fps 60
```

启动后会弹出六个图像窗口

## 程序使用方法
### 传感器数据读取
使用以下回调函数分别进行获取
```
capture_frames_callback  //摄像头帧采集回调函数
tactile_callback         //触觉数据回调函数
encoder_callback         //夹爪开合度数据回调函数
```

### 夹爪开合控制指令下发
使用以下指令
```
if self.system.databus:
    self.system.databus.set_target_distance(value)
```

## 设备相关参数获取 

### 直接运行脚本
```
python3 scripts/camera_cmd.py <参数>
```

```

**参数说明：**

| 参数       | 说明                                |
|----------- |------------------------------------|
| `camerarc`| 中间相机标定（生成 `cam0_sensor.yaml`）|
| `camerarl`| 左侧相机标定（生成 `cam1_sensor.yaml`）|
| `camerarr`| 右侧相机标定（生成 `cam2_sensor.yaml`）|
| `MCUID`   | 查询设备 MCUID                         |

**标定生成的 YAML 文件** 会保存到 `scripts/calib_result/` 目录下。
```
### **示例：**


### 单夹爪
#### 获取相机标定文件
```
中间相机
python3 scripts/camera_cmd.py camerarc  
左边相机
python3 scripts/camera_cmd.py camerarl
右边相机
python3 scripts/camera_cmd.py camerarr
```
#### 查询设备 ID
```
python3 scripts/camera_cmd.py MCUID
```
### 双夹爪
#### 获取相机标定文件
```
中间相机
python3 scripts/camera_cmd.py left camerarc  
python3 scripts/camera_cmd.py right camerarc
左边相机
python3 scripts/camera_cmd.py left camerarl 
python3 scripts/camera_cmd.py right camerarl
右边相机
python3 scripts/camera_cmd.py left camerarr  
python3 scripts/camera_cmd.py right camerarr
```

#### 查询设备 ID
```
python3 scripts/camera_cmd.py left MCUID
python3 scripts/camera_cmd.py right MCUID
```