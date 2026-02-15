import socket
import struct
import os

DEBUG = False

if DEBUG:
    SERVER_IP = "127.0.0.6"
else:
    SERVER_IP = "95.181.175.77"

SERVER_PORT = 53255  # sin_port = 2000 без htons на x86
PAYLOAD = 1024 * 16
PACKET_SIZE = PAYLOAD + 4


def robust_send(sock, data):
    sock.sendall(data)


def count_subdirectories(path):
    if not os.path.isdir(path):
        return 0
    return sum(1 for entry in os.listdir(path)
               if os.path.isdir(os.path.join(path, entry)))


def send_cmd(sock, cmd):
    buf = bytearray(PACKET_SIZE)
    buf[0:4] = cmd.encode("ascii")
    robust_send(sock, bytes(buf))


def send_file(sock, filepath, name, filetype):
    filesize = os.path.getsize(filepath)

    # Заголовок: [TYPE 4б][SIZE 8б][NAME 128б][...padding...]
    buf = bytearray(PACKET_SIZE)
    buf[0:4] = filetype.encode("ascii")
    struct.pack_into("<q", buf, 4, filesize)  # long long, little-endian
    name_bytes = name.encode("ascii")
    buf[12:12 + len(name_bytes)] = name_bytes
    robust_send(sock, bytes(buf))

    # Данные: [WRIT 4б][DATA 1024б]
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(PAYLOAD)
            if not chunk:
                break
            buf = bytearray(PACKET_SIZE)
            buf[0:4] = b"WRIT"
            buf[4:4 + len(chunk)] = chunk
            robust_send(sock, bytes(buf))

    send_cmd(sock, "CLOS")


def recv_exact(sock, n):
    """Читает ровно n байт из сокета"""
    data = bytearray()
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            return None
        data.extend(chunk)
    return bytes(data)


def main():
    num_dirs = count_subdirectories("pc_dir")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((SERVER_IP, SERVER_PORT))
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    # --- Отправка ---
    send_cmd(sock, "INIT")
    send_file(sock, "pc_dir/config.mat", "cfg", "CONF")

    for i in range(1, num_dirs + 1):
        send_file(sock, f"pc_dir/{i}/tx_data.mat", str(i), "FILE")

    send_cmd(sock, "STAR")

    # --- Прием ---
    rx_count = 0
    file_open = False
    file = None
    size = 0

    while True:
        buf = recv_exact(sock, PACKET_SIZE)
        if buf is None:
            break

        header = buf[0:4]

        if header == b"FILE" and not file_open:
            rx_count += 1
            size = struct.unpack_from("<q", buf, 4)[0]
            filename = f"pc_dir/{rx_count}/rx_data.mat"
            print(f"PC: FILE {filename}")
            file = open(filename, "wb")
            file_open = True

        elif header == b"WRIT" and file_open:
            to_write = min(size, PAYLOAD)
            file.write(buf[4:4 + to_write])
            size -= to_write

        elif header == b"CLOS" and file_open:
            print(f"PC: CLOSE {filename}")
            file.close()
            file_open = False

        elif header == b"STAR":
            print("PC: END")
            if file_open:
                file.close()
            break

    sock.close()


if __name__ == "__main__":
    main()
