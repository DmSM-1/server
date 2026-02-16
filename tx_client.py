import socket
import struct
import os
import scipy.io
import numpy as np
import sdr
import subprocess
import time

DEBUG = False
times = 4

if DEBUG:
    SERVER_IP = "127.0.0.6"
else:
    SERVER_IP = "95.181.175.77"

TX_PORT = 53511  # sin_port = 2001 без htons на x86
PAYLOAD = 1024 * 16
PACKET_SIZE = PAYLOAD + 4


def robust_send(sock, data):
    sock.sendall(data)


def send_cmd(sock, cmd):
    buf = bytearray(PACKET_SIZE)
    buf[0:4] = cmd.encode("ascii")
    robust_send(sock, bytes(buf))


def recv_exact(sock, n):
    data = bytearray()
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            return None
        data.extend(chunk)
    return bytes(data)


def parse_config(filepath):
    """Парсит config.mat и возвращает словарь со всеми параметрами."""
    mat = scipy.io.loadmat(filepath, squeeze_me=True)
    opts = mat['options']

    # Извлекаем все поля из MATLAB struct в Python dict
    config = {}
    for field in opts.dtype.names:
        val = opts[field].item()
        # numpy массивы оставляем как есть, скаляры разворачиваем
        if isinstance(val, np.ndarray):
            if val.ndim == 0:
                val = val.item()
        config[field] = val

    return config


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    sock.connect((SERVER_IP, TX_PORT))

    print("TX client: connected")

    os.makedirs("tx_buf", exist_ok=True)

    file_open = False
    file = None
    filename = ""
    size = 0

    while True:
        buf = recv_exact(sock, PACKET_SIZE)
        if buf is None:
            print("TX client: connection closed")
            break

        header = buf[0:4]

        if header == b"CONF" and not file_open:
            size = struct.unpack_from("<q", buf, 4)[0]
            filename = "tx_buf/cfg"
            file = open(filename, "wb", buffering=1024 * 1024)
            file_open = True
            print(f"TX: receiving config ({size} bytes)")

        elif header == b"FILE" and not file_open:
            size = struct.unpack_from("<q", buf, 4)[0]
            name_raw = buf[12:140]
            name = name_raw.split(b"\x00")[0].decode("ascii", errors="ignore")
            filename = f"tx_buf/{name}"
            file = open(filename, "wb", buffering=1024 * 1024)
            file_open = True
            print(f"TX: receiving {filename} ({size} bytes)")

        elif header == b"WRIT" and file_open:
            to_write = min(size, PAYLOAD)
            file.write(buf[4:4 + to_write])
            size -= to_write

        elif header == b"CLOS" and file_open:
            file.close()
            file_open = False
            print(f"TX: saved {filename}")

        elif header == b"STAR":
            if file_open:
                file.close()
                file_open = False
            print("TX: all files received")
            break

    config = parse_config("rx_buf/cfg")

    print("\n=== Parsed Config ===")
    for key, val in config.items():
        if isinstance(val, np.ndarray):
            print(f"  {key:20s} = array{val.shape}")
        else:
            print(f"  {key:20s} = {val}")

    N           = config['N']               # FFT size (1024)
    L           = config['L']               # CP length (32)
    Fs          = config['Fs']              # Sample rate (20e6)
    Fc          = config['Fc']              # Carrier freq (2.4e9)
    sdr_order   = config['sdr_order']       # SDR order (1)

    print(f"\n=== Key Parameters ===")
    print(f"  N={N}, L={L}, Fs={Fs/1e6:.0f} MHz, Fc={Fc/1e9:.1f} GHz")
    print(f"  SDR order={sdr_order}")

    
    s = subprocess.run(["iio_attr", "-S"], capture_output=True, text=True).stdout.split('\n')
    sdr_usb = []
    for i in s:
        if "PlutoSDR" in i and "usb" in i:
            sdr_usb.append(i.split(' ')[-1][1:-1])



    tx_files = sorted(
        [f for f in os.listdir("tx_buf") if f != "cfg" and os.path.isfile(f"tx_buf/{f}")],
        key=lambda x: int(x)
    )

    print(f"Found {len(tx_files)} TX files")

    for fname in tx_files:
        filepath = f"tx_buf/{fname}"
        print(f"Processing {filepath}...")

        mat_data = scipy.io.loadmat(filepath, squeeze_me=True)
        tx_waveform = mat_data['tx_waveform']

        tx_waveform = tx_waveform.flatten() * (2**12)

        STA = sdr.SDR(sdr_usb[0], Fc, Fs, tx_cycle_buffer=1)
        padding = np.zeros(10 * STA.buffer_size, dtype=tx_waveform.dtype)
        tx_waveform = np.concatenate([padding, tx_waveform])

        print(f"  Waiting for ACTV...")
        buf = recv_exact(sock, PACKET_SIZE)
        if buf is None or buf[0:4] != b"ACTV":
            break
        print(f"  ACTV received")

        STA.send(tx_waveform)
        time.sleep(10)
        t = time.time()
        print(f"  Sent: {len(tx_waveform)} samples at {time.strftime('%H:%M:%S', time.localtime(t))}.{int((t % 1) * 1e6):06d}")

        send_cmd(sock, "STAR")

        del STA

    print("TX: done")
    sock.close()


if __name__ == "__main__":
    main()
