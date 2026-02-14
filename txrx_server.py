import socket
import struct
import os
import threading

DEBUG = False

if DEBUG:
    SERVER_IP = "127.0.0.10"
else:
    SERVER_IP = "95.181.175.77"

SERVER_PORT = 53255  # sin_port = 2000 без htons на x86
PAYLOAD = 1024 * 16
PACKET_SIZE = PAYLOAD + 4
TIMES = 4
NUM_LINKS = 4  # Количество параллельных TCP-соединений


def clear_dir(path):
    if not os.path.isdir(path):
        return
    for entry in os.listdir(path):
        full_path = os.path.join(path, entry)
        if os.path.isfile(full_path):
            os.unlink(full_path)


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


def send_cmd(sock, cmd):
    buf = bytearray(PACKET_SIZE)
    buf[0:4] = cmd.encode("ascii")
    robust_send(sock, bytes(buf))


def send_file_over_link(sock, filepath, name, filetype):
    """Отправляет один файл через одно соединение."""
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

    buf = bytearray(PACKET_SIZE)
    buf[0:4] = b"CLOS"
    robust_send(sock, bytes(buf))


# ============================================================
# MULTILINK: Отправка файлов параллельно через несколько TCP
# ============================================================

def send_worker(sock, file_list):
    """
    Поток-отправщик: берёт список файлов и отправляет их
    через своё TCP-соединение последовательно.
    В конце шлёт STAR (конец потока).
    """
    for filepath, name in file_list:
        send_file_over_link(sock, filepath, name, "FILE")
    send_cmd(sock, "STAR")


def multilink_send(sockets, num_dirs):
    """
    Распределяет файлы по соединениям (Round-Robin)
    и запускает параллельную отправку.

    Пример с 4 линками и 8 файлами:
      Link 0: файлы 1, 5
      Link 1: файлы 2, 6
      Link 2: файлы 3, 7
      Link 3: файлы 4, 8
    """
    # Распределяем файлы по линкам (Round-Robin)
    file_lists = [[] for _ in range(len(sockets))]
    for i in range(1, num_dirs + 1):
        link_idx = (i - 1) % len(sockets)
        filepath = f"buf/tx/{i}"
        file_lists[link_idx].append((filepath, str(i)))

    # Запускаем потоки отправки
    threads = []
    for i, sock in enumerate(sockets):
        t = threading.Thread(target=send_worker, args=(sock, file_lists[i]))
        t.start()
        threads.append(t)

    # Ждём завершения всех потоков
    for t in threads:
        t.join()


# ============================================================
# MULTILINK: Приём файлов параллельно через несколько TCP
# ============================================================

def recv_worker(sock, received_files, lock):
    """
    Поток-приёмщик: читает файлы из своего TCP-соединения
    до получения STAR (конец потока).
    Складывает принятые данные в общий словарь received_files.
    """
    file_open = False
    file = None
    filename = ""
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
            filename = f"buf/rx/{name}"
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
    """
    Запускает параллельный приём со всех соединений.
    Возвращает словарь принятых файлов.
    """
    received_files = {}
    lock = threading.Lock()

    threads = []
    for sock in sockets:
        t = threading.Thread(target=recv_worker, args=(sock, received_files, lock))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    return received_files


# ============================================================
# УПРАВЛЯЮЩЕЕ СОЕДИНЕНИЕ (Link 0 = control link)
# ============================================================

def configure_socket(sock):
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)


def pc_handler(init_tx, init_rx, end_tx, end_rx):
    """
    Основной обработчик:
    1. Принимает NUM_LINKS TCP-соединений от клиента.
    2. Link 0 = управляющий (принимает INIT, CONF, FILE, STAR).
    3. При отправке обратно — файлы распределяются по всем линкам.
    """
    sfd = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sfd.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    configure_socket(sfd)
    sfd.bind((SERVER_IP, SERVER_PORT))

    for iteration in range(TIMES):
        sfd.listen(NUM_LINKS)

        # Принимаем NUM_LINKS соединений от клиента
        sockets = []
        for link_id in range(NUM_LINKS):
            conn, addr = sfd.accept()
            configure_socket(conn)
            sockets.append(conn)
            print(f"  Link {link_id} connected from {addr}")

        print(f"All {NUM_LINKS} links established (iter {iteration})")

        # === ФАЗА 1: Приём данных от клиента (через link 0 — управляющий) ===
        ctrl = sockets[0]
        file_open = False
        file = None
        filename = ""
        size = 0
        num_dirs = 0

        while True:
            buf = recv_exact(ctrl, PACKET_SIZE)
            if buf is None:
                break

            header = buf[0:4]

            if header == b"INIT":
                print("PC: INIT")
                clear_dir("./buf/rx")
                clear_dir("./buf/tx")

            elif header == b"CONF" and not file_open:
                print("PC: CONF")
                size = struct.unpack_from("<q", buf, 4)[0]
                filename = "buf/cfg"
                file = open(filename, "wb", buffering=1024 * 1024)
                file_open = True

            elif header == b"FILE" and not file_open:
                size = struct.unpack_from("<q", buf, 4)[0]
                name_raw = buf[12:140]
                name = name_raw.split(b"\x00")[0].decode("ascii", errors="ignore")
                filename = f"buf/tx/{name}"
                print(f"PC: FILE {filename}")
                file = open(filename, "wb", buffering=1024 * 1024)
                file_open = True
                num_dirs += 1

            elif header == b"WRIT" and file_open:
                to_write = min(size, PAYLOAD)
                file.write(buf[4:4 + to_write])
                size -= to_write

            elif header == b"CLOS" and file_open:
                print(f"PC: CLOSE {filename}")
                file.close()
                file_open = False

            elif header == b"STAR":
                print("PC: START")
                if file_open:
                    file.close()
                    file_open = False
                break

        print("PC: INIT END")

        # === ФАЗА 2: Обработка (tx/rx потоки) ===
        init_tx.set()
        init_rx.set()

        end_tx.wait()
        end_tx.clear()
        end_rx.wait()
        end_rx.clear()

        # === ФАЗА 3: Отправка результатов ПАРАЛЛЕЛЬНО через все линки ===
        print(f"Sending {num_dirs} files over {NUM_LINKS} links...")
        multilink_send(sockets, num_dirs)
        print("Send complete.")

        # Закрываем все соединения
        for sock in sockets:
            sock.close()

    sfd.close()


def tx_handler(init_tx, end_tx):
    for _ in range(TIMES):
        init_tx.wait()
        init_tx.clear()
        # === Ваша логика обработки TX ===
        end_tx.set()


def rx_handler(init_rx, end_rx):
    for _ in range(TIMES):
        init_rx.wait()
        init_rx.clear()
        # === Ваша логика обработки RX ===
        end_rx.set()


def main():
    os.makedirs("buf/rx", exist_ok=True)
    os.makedirs("buf/tx", exist_ok=True)

    init_tx = threading.Event()
    init_rx = threading.Event()
    end_tx = threading.Event()
    end_rx = threading.Event()

    pc_thread = threading.Thread(target=pc_handler, args=(init_tx, init_rx, end_tx, end_rx))
    tx_thread = threading.Thread(target=tx_handler, args=(init_tx, end_tx))
    rx_thread = threading.Thread(target=rx_handler, args=(init_rx, end_rx))

    pc_thread.start()
    tx_thread.start()
    rx_thread.start()

    pc_thread.join()
    tx_thread.join()
    rx_thread.join()

    print("Server finished.")


if __name__ == "__main__":
    main()
