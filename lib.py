import socket

def send_syslog(message, port=514, hostname="picopower", appname="main", procid="-", msgid="-"):
    print(message)

    syslog_addr = ('255.255.255.255', port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    pri = 13  # user.notice
    version = 1
    syslog_msg = f"<{pri}>{version} {hostname} {appname} {procid} {msgid} - {message}\r\n".encode('utf-8')
    try:
        sock.sendto(syslog_msg, syslog_addr)
    except Exception as ex:
        print(f"Syslog send failed: {ex}")
    finally:
        sock.close()

