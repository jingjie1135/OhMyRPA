"""scrcpy server 手动连通性检查。

注意：这是需要真实 ADB 设备 + scrcpy server 环境的手动集成脚本，
不是 unittest 用例。所有逻辑都放在 main() 内并由 __main__ 守卫，
确保 `python -m unittest discover` 在无设备环境下导入本模块时
不会执行设备操作、也不会 sys.exit 中断整个测试发现流程。

手动运行：python test_scrcpy.py
"""

import socket
import subprocess
import sys
from pathlib import Path


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import config

    adb = config.ADB_PATH
    # Find device
    r = subprocess.run([adb, "devices"], capture_output=True, text=True)
    device_id = ""
    for line in r.stdout.splitlines()[1:]:
        if "device" in line:
            device_id = line.split()[0]
            break

    if not device_id:
        print("No device")
        return 1

    subprocess.run([adb, "-s", device_id, "reverse", "localabstract:testsc", "tcp:27183"])
    ls = socket.socket()
    ls.bind(("127.0.0.1", 27183))
    ls.listen(1)

    cmd = [adb, "-s", device_id, "shell", "CLASSPATH=/data/local/tmp/scrcpy-server.jar", "app_process", "/", "com.genymobile.scrcpy.Server", "3.3.3", "video=false", "audio=false", "control=true", "scid=1234"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    conn, addr = ls.accept()
    print("accepted!")
    data = conn.recv(1024)
    print("data:", data)
    p.terminate()
    subprocess.run([adb, "-s", device_id, "reverse", "--remove-all"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
