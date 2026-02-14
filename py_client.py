import socket
import struct
import os
import threading

DEBUG = False

if DEBUG:
    SERVER_IP = "127.0.0.10"
else:
    SERVER_IP = "95.181.175.77"

SERVER_PORT = 53255
PAYLOAD = 1024 * 16
PACKET_SIZE = PAYLOAD + 4
NUM_LINKS = 4  # Должно совпадать с сервером!


def robust_send(sock, data):
    sock.sendall(data)


def recv_exact(sock, n):
    data = bytearray()
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            return None
        data.extend(chunk)
    return bytes(data)


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


def configure_socket(sock):
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)


# ============================================================
# MULTILINK: Приём файлов параллельно через несколько TCP
# ============================================================

def recv_worker(sock, received_files, lock):
    """
    Принимает файлы из одного TCP-соединения до получения STAR.
    """
    file_open = False
    file = None
    size = 0

    while True:
        buf = recv_exact(sock, PACKET_SIZE)
        if buf is None:
            break

        header = buf[0:4]

        if header == b"FILE" and not file_open:
            size = struct.unpack_from("<q", buf, 4)[0]
            name_raw = buf[12:140]
            name = name_raw.split(b"\x00")[0].decode("ascii", errors="ignore")

            # Создаём директорию если нужно
            dir_path = f"pc_dir/{name}"
            os.makedirs(dir_path, exist_ok=True)
            filename = f"{dir_path}/{name}"

            print(f"  Link -> FILE {filename}")
            file = open(filename, "wb", buffering=1024 * 1024)
            file_open = True

        elif header == b"WRIT" and file_open:
            to_write = min(size, PAYLOAD)
            file.write(buf[4:4 + to_write])
            size -= to_write

        elif header == b"CLOS" and file_open:
            file.close()
            file_open = False
            with lock:
                received_files[filename] = True

        elif header == b"STAR":
            if file_open:
                file.close()
            break


def multilink_recv(sockets):
    """Запускает параллельный приём со всех линков."""
    received_files = {}
    lock = threading.Lock()

    threads = []
    for i, sock in enumerate(sockets):
        t = threading.Thread(target=recv_worker, args=(sock, received_files, lock))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    return received_files


def main():
    num_dirs = count_subdirectories("pc_dir")

    # === Устанавливаем NUM_LINKS TCP-соединений к серверу ===
    sockets = []
    for i in range(NUM_LINKS):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        configure_socket(sock)
        sock.connect((SERVER_IP, SERVER_PORT))
        sockets.append(sock)
        print(f"  Link {i} connected")

    print(f"All {NUM_LINKS} links established")

    # === ОТПРАВКА через link 0 (управляющий) ===
    ctrl = sockets[0]

    send_cmd(ctrl, "INIT")
    send_file(ctrl, "pc_dir/config.mat", "cfg", "CONF")

    for i in range(1, num_dirs + 1):
        send_file(ctrl, f"pc_dir/{i}/tx_data.mat", str(i), "FILE")

    send_cmd(ctrl, "STAR")
    print("Send complete. Waiting for RX...")

    # === ПРИЁМ через ВСЕ линки параллельно ===
    received = multilink_recv(sockets)
    print(f"Received {len(received)} files")

    # Закрываем все соединения
    for sock in sockets:
        sock.close()


if __name__ == "__main__":
    main()
