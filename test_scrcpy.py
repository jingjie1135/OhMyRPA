import socket, subprocess, time, sys

sys.path.insert(0, "g:/Users/Administrator/Documents/AI/antigravity/游戏脚本/百龙霸业/0.1")
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
    sys.exit(1)

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
