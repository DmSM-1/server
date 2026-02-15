import socket
import struct
import os
import scipy.io
import numpy as np
import sdr
import subprocess
import time

import matplotlib.pyplot as plt

DEBUG = False

if DEBUG:
    SERVER_IP = "127.0.0.6"
else:
    SERVER_IP = "95.181.175.77"

RX_PORT = 53767  # sin_port = 2002 без htons
PAYLOAD = 1024 * 16
PACKET_SIZE = PAYLOAD + 4


def robust_send(sock, data):
    sock.sendall(data)


def send_cmd(sock, cmd):
    buf = bytearray(PACKET_SIZE)
    buf[0:4] = cmd.encode("ascii")
    robust_send(sock, bytes(buf))


def send_file(sock, filepath, name, filetype):
    filesize = os.path.getsize(filepath)

    buf = bytearray(PACKET_SIZE)
    buf[0:4] = filetype.encode("ascii")
    struct.pack_into("<q", buf, 4, filesize)
    name_bytes = name.encode("ascii")
    buf[12:12 + len(name_bytes)] = name_bytes
    robust_send(sock, bytes(buf))

    with open(filepath, "rb") as f:
        while True:
            buf = bytearray(PACKET_SIZE)
            buf[0:4] = b"WRIT"
            n = f.readinto(memoryview(buf)[4:])
            if n == 0:
                break
            robust_send(sock, bytes(buf))

    send_cmd(sock, "CLOS")

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
    sock.connect((SERVER_IP, RX_PORT))

    print("RX client: connected")

    os.makedirs("rx_buf", exist_ok=True)

    while True:
        buf = recv_exact(sock, PACKET_SIZE)
        if buf is None:
            print("RX client: connection closed")
            break

        header = buf[0:4]

        if header == b"CONF":
            size = struct.unpack_from("<q", buf, 4)[0]
            filename = "rx_buf/cfg"
            file = open(filename, "wb")
            print(f"RX: receiving config ({size} bytes)")

            while size > 0:
                buf = recv_exact(sock, PACKET_SIZE)
                if buf is None:
                    break
                if buf[0:4] == b"WRIT":
                    to_write = min(size, PAYLOAD)
                    file.write(buf[4:4 + to_write])
                    size -= to_write
                elif buf[0:4] == b"CLOS":
                    break

            file.close()
            print("RX: config saved")

        elif header == b"STAR":
            print("RX: START received")
            break

    # --- Парсим config ---
    config = parse_config("rx_buf/cfg")

    print("\n=== Parsed Config ===")
    for key, val in config.items():
        if isinstance(val, np.ndarray):
            print(f"  {key:20s} = array{val.shape}")
        else:
            print(f"  {key:20s} = {val}")

    # Основные параметры доступны как:
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

    os.makedirs("rx_buf/data", exist_ok=True)

    frame_idx = 1
    while True:
        # Ждём команду ACTV от сервера
        print(f"\nWaiting for ACTV (frame {frame_idx})...")
        STA = sdr.SDR(sdr_usb[1], Fc, Fs, buffer_size=2**16*100)
        buf = recv_exact(sock, PACKET_SIZE)
        if buf is None:
            print("Connection closed")
            break
        if buf[0:4] == b"STAR":
            print("STAR received, stopping")
            break
        if buf[0:4] != b"ACTV":
            print(f"Unexpected: {buf[0:4]}")
            continue

        print(f"ACTV received, recording...")

        # Приём с SDR
        send_cmd(sock, "RECV")
        rx_waveform = np.array(STA.recv(), dtype=np.complex128).reshape(-1, 1)

        t = time.time()
        print(f"  Recv: {rx_waveform.shape[0]} samples at {time.strftime('%H:%M:%S', time.localtime(t))}.{int((t % 1) * 1e6):06d}")


        plt.plot(abs(rx_waveform))
        plt.show()

        # Сохраняем как .mat (1, 2, 3, ...)
        filepath = f"rx_buf/data/{frame_idx}.mat"
        scipy.io.savemat(filepath, {'rx_waveform': rx_waveform})

        print(f"Saved {filepath} ({rx_waveform.shape[0]} samples)")

        frame_idx += 1

        del STA
    
    print(f"RX: done, saved {frame_idx - 1} files")

    # === Отправляем файлы обратно на сервер ===    
    rx_files = sorted(
        [f for f in os.listdir("rx_buf/data") if f.endswith(".mat")],
        key=lambda x: int(x.replace(".mat", ""))
    )

    for fname in rx_files:
        filepath = f"rx_buf/data/{fname}"
        send_file(sock, filepath, fname, "FILE")


    send_cmd(sock, "STAR")
    print("RX: all files sent")

    sock.close()


if __name__ == "__main__":
    config = main()