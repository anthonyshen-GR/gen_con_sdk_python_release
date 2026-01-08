#!/usr/bin/env python3
# 加密的__init__.py模块
import sys
import os
import base64
import types

# 设置路径
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
  sys.path.insert(0, _script_dir)

# 编码的源码
ENCODED_SOURCE = '''
IiIiCkdlbiBDb250cm9sbGVyIFNESyAtIFB1cmUgUHl0aG9uIEltcGxlbWVudGF0aW9uCkEgcHVyZSBQeXRob24gU0RLIGZvciBjb250cm9sbGluZyBncmlwcGVyIGRldmljZXMgd2l0aG91dCBST1MgZGVwZW5kZW5jeS4KIiIiCgpfX3ZlcnNpb25fXyA9ICIxLjAuMCIKCmZyb20gLnN5c3RlbSBpbXBvcnQgR3JpcHBlclN5c3RlbQpmcm9tIC5kYXRhYnVzIGltcG9ydCBEYXRhQnVzLCBmaW5kX3NlcmlhbF9wb3J0CmZyb20gLmNhbWVyYSBpbXBvcnQgQ2FtZXJhQ2FwdHVyZQoKX19hbGxfXyA9IFsKICAgICdHcmlwcGVyU3lzdGVtJywKICAgICdEYXRhQnVzJywKICAgICdmaW5kX3NlcmlhbF9wb3J0JywKICAgICdDYW1lcmFDYXB0dXJlJywKXQo=
'''

def _decode_and_execute():
  """解码并执行源码，返回模块的全局命名空间"""
  try:
    source_code = base64.b64decode(ENCODED_SOURCE).decode('utf-8')
    code = compile(source_code, '__init__.py', 'exec')
    
    import builtins
    globals_dict = {
      '__name__': 'gen_controller_sdk_python',
      '__file__': __file__,
      '__package__': 'gen_controller_sdk_python',
      '__builtins__': builtins,
    }
    
    exec(code, globals_dict)
    return globals_dict
  except Exception as e:
    print(f"解码错误: {e}")
    import traceback
    traceback.print_exc()
    raise

# 解码并获取原始模块的全局命名空间
_original_globals = _decode_and_execute()

# 导出原始模块的所有非私有符号
for name, value in _original_globals.items():
  if not name.startswith('_') and name not in globals():
    globals()[name] = value

# 定义__all__列表
__all__ = []
for name in _original_globals.keys():
  if not name.startswith('_'):
    __all__.append(name)
globals()['__all__'] = __all__

# 导出版本信息
__version__ = _original_globals.get('__version__', '1.0.0')
