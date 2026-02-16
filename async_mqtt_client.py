"""
Async MQTT client for MicroPython using asyncio
Native async/await implementation
"""

import asyncio
import struct
import select


class MQTTException(Exception):
    pass


class AsyncMQTTClient:
    """Async MQTT client using asyncio streams"""

    def __init__(self, client_id, server, port=0, user=None, password=None, keepalive=0,
                 ssl=False, ssl_params={}):
        """Initialize MQTT client

        Args:
            client_id: String client identifier
            server: String hostname or IP address
            port: Port number (default: 1883 for non-SSL, 8883 for SSL)
            user: Optional string username
            password: Optional string password
            keepalive: Keepalive interval in seconds
            ssl: Enable SSL/TLS
            ssl_params: SSL parameters dict
        """
        if port == 0:
            port = 8883 if ssl else 1883
        self.client_id = client_id.encode('utf-8')
        self.sock = None
        self.server = server
        self.port = port
        self.ssl = ssl
        self.ssl_params = ssl_params
        self.pid = 0
        self.cb = None
        self.user = user.encode('utf-8') if user else None
        self.pswd = password.encode('utf-8') if password else None
        self.keepalive = keepalive
        self.lw_topic = None
        self.lw_msg = None
        self.lw_qos = 0
        self.lw_retain = False
        self._reader = None
        self._writer = None

    def set_callback(self, f):
        """Set callback for incoming messages"""
        self.cb = f

    def set_last_will(self, topic, msg, retain=False, qos=0):
        """Set last will and testament

        Args:
            topic: String topic (will be UTF-8 encoded)
            msg: Bytes payload (caller must encode strings to bytes)
        """
        if not (0 <= qos <= 2):
            raise ValueError(f"MQTT: Invalid QoS {qos}, must be 0-2")
        if not topic:
            raise ValueError("MQTT: Topic cannot be empty")
        if not isinstance(msg, bytes):
            raise TypeError(f"msg must be bytes, got {type(msg).__name__}")
        self.lw_topic = topic.encode('utf-8')
        self.lw_msg = msg
        self.lw_qos = qos
        self.lw_retain = retain

    async def connect(self, clean_session=True):
        """Async connect using asyncio streams"""
        try:
            # Import socket here to avoid issues
            import socket as socket_module

            # Create socket manually
            self.sock = socket_module.socket()
            self.sock.setblocking(False)

            # Get address info
            addr = socket_module.getaddrinfo(self.server, self.port)[0][-1]

            # Non-blocking connect
            try:
                self.sock.connect(addr)
            except OSError as e:
                # EINPROGRESS is expected for non-blocking connect
                if e.errno not in (115, 119):  # EINPROGRESS, EALREADY
                    raise

            # Wait for connection to complete
            await asyncio.sleep_ms(100)

            # Wrap socket with asyncio streams
            self._reader = asyncio.StreamReader(self.sock)
            self._writer = asyncio.StreamWriter(self.sock, {})

            # Perform MQTT CONNECT handshake
            # Build CONNECT packet
            premsg = bytearray(b"\x10\0\0\0\0\0")
            msg = bytearray(b"\x04MQTT\x04\x02\0\0")

            sz = 10 + 2 + len(self.client_id)
            msg[6] = clean_session << 1
            if self.user is not None:
                sz += 2 + len(self.user) + 2 + len(self.pswd)
                msg[6] |= 0xC0
            if self.keepalive:
                msg[7] |= self.keepalive >> 8
                msg[8] |= self.keepalive & 0x00FF
            if self.lw_topic:
                sz += 2 + len(self.lw_topic) + 2 + len(self.lw_msg)
                msg[6] |= 0x4 | (self.lw_qos & 0x1) << 3 | (self.lw_qos & 0x2) << 3
                msg[6] |= self.lw_retain << 5

            i = 1
            while sz > 0x7f:
                premsg[i] = (sz & 0x7f) | 0x80
                sz >>= 7
                i += 1
            premsg[i] = sz

            # Send CONNECT packet
            self._writer.write(premsg[:i + 2])
            self._writer.write(msg)
            self._send_str(self.client_id)
            if self.lw_topic:
                self._send_str(self.lw_topic)
                self._send_str(self.lw_msg)
            if self.user is not None:
                self._send_str(self.user)
                self._send_str(self.pswd)
            await self._writer.drain()

            # Wait for CONNACK
            resp = await self._reader.readexactly(4)
            if resp[0] != 0x20 or resp[1] != 0x02:
                raise MQTTException(resp)
            if resp[3] != 0:
                raise MQTTException(resp[3])

            return resp[2] & 1

        except Exception as e:
            if self.sock:
                try:
                    self.sock.close()
                except:
                    pass
            self.sock = None
            self._reader = None
            self._writer = None
            raise

    def _send_str(self, s):
        """Helper to send a length-prefixed string"""
        self._writer.write(struct.pack("!H", len(s)))
        self._writer.write(s)

    async def disconnect(self):
        """Async disconnect"""
        try:
            if self._writer:
                self._writer.write(b"\xe0\0")
                await self._writer.drain()
        finally:
            if self.sock:
                self.sock.close()
            self._reader = None
            self._writer = None
            self.sock = None

    async def ping(self):
        """Async ping"""
        self._writer.write(b"\xc0\0")
        await self._writer.drain()

    async def publish(self, topic, msg, retain=False, qos=0):
        """Async publish

        Args:
            topic: String topic (will be UTF-8 encoded)
            msg: Bytes payload (caller must encode strings to bytes)
        """
        # Topics are always strings in MQTT, encode to UTF-8
        topic_bytes = topic.encode('utf-8')

        # Payload must be bytes - caller's responsibility to encode
        if not isinstance(msg, bytes):
            raise TypeError(f"msg must be bytes, got {type(msg).__name__}")

        msg_bytes = msg

        pkt = bytearray(b"\x30\0\0\0")
        pkt[0] |= qos << 1 | retain
        sz = 2 + len(topic_bytes) + len(msg_bytes)
        if qos > 0:
            sz += 2
        if sz >= 2097152:
            raise MQTTException("Message too long")
        i = 1
        while sz > 0x7f:
            pkt[i] = (sz & 0x7f) | 0x80
            sz >>= 7
            i += 1
        pkt[i] = sz
        self._writer.write(pkt[:i + 1])
        self._send_str(topic_bytes)
        if qos > 0:
            self.pid += 1
            pid = self.pid
            self._writer.write(struct.pack("!H", pid))
        self._writer.write(msg_bytes)
        await self._writer.drain()

        if qos == 1:
            # Wait for PUBACK
            while True:
                op = await self._wait_msg_internal()
                if op == 0x40:
                    # PUBACK received
                    sz = await self._reader.readexactly(1)
                    if sz[0] != 0x02:
                        raise MQTTException(f"Invalid PUBACK size: {sz[0]}")
                    rcv_pid = await self._reader.readexactly(2)
                    rcv_pid = struct.unpack("!H", rcv_pid)[0]
                    if pid == rcv_pid:
                        return
        elif qos == 2:
            raise NotImplementedError("QoS 2 not supported")

    async def publish_string(self, topic, msg, retain=False, qos=0, encoding='utf-8'):
        """Convenience method to publish string payloads

        Args:
            topic: String topic
            msg: String payload (will be encoded to bytes)
            retain: Retain flag
            qos: Quality of Service (0, 1, or 2)
            encoding: Character encoding (default: utf-8)

        Example:
            await client.publish_string("home/temp", "23.5")
            await client.publish_string("home/data", json.dumps(data))
        """
        return await self.publish(topic, msg.encode(encoding), retain, qos)

    async def subscribe(self, topic, qos=0):
        """Async subscribe

        Args:
            topic: String topic (will be UTF-8 encoded)
        """
        if not self.cb:
            raise MQTTException("Callback not set")

        topic_bytes = topic.encode('utf-8')

        pkt = bytearray(b"\x82\0\0\0")
        self.pid += 1
        struct.pack_into("!BH", pkt, 1, 2 + 2 + len(topic_bytes) + 1, self.pid)
        self._writer.write(pkt)
        self._send_str(topic_bytes)
        self._writer.write(qos.to_bytes(1, "little"))
        await self._writer.drain()

        # Wait for SUBACK
        while True:
            op = await self._wait_msg_internal()
            if op == 0x90:
                # SUBACK received
                resp = await self._reader.readexactly(4)
                return

    async def _wait_msg_internal(self):
        """Internal method to read next packet type"""
        res = await self._reader.readexactly(1)
        if res == b"":
            raise OSError(-1)
        return res[0]

    async def wait_msg(self):
        """Async wait for incoming message"""
        res = await self._reader.readexactly(1)
        if res == b"":
            raise OSError(-1)

        if res == b"\xd0":  # PINGRESP
            sz = await self._reader.readexactly(1)
            if sz[0] != 0:
                raise MQTTException(f"Invalid PINGRESP size: {sz[0]}")
            return None

        op = res[0]
        if op & 0xF0 != 0x30:
            return op

        # PUBLISH packet
        sz = await self._recv_len()
        topic_len_data = await self._reader.readexactly(2)
        topic_len = (topic_len_data[0] << 8) | topic_len_data[1]
        topic = await self._reader.readexactly(topic_len)
        sz -= topic_len + 2

        if op & 6:
            pid_data = await self._reader.readexactly(2)
            pid = (pid_data[0] << 8) | pid_data[1]
            sz -= 2

        msg = await self._reader.readexactly(sz)

        # Call callback with decoded topic string and raw message bytes
        if self.cb:
            self.cb(topic.decode('utf-8'), msg)

        # Send PUBACK if QoS 1
        if op & 6 == 2:
            pkt = bytearray(b"\x40\x02\0\0")
            struct.pack_into("!H", pkt, 2, pid)
            self._writer.write(pkt)
            await self._writer.drain()
        elif op & 6 == 4:
            raise NotImplementedError("QoS 2 not supported")

        return op

    async def _recv_len(self):
        """Async receive variable length"""
        n = 0
        sh = 0
        while True:
            b = await self._reader.readexactly(1)
            b = b[0]
            n |= (b & 0x7f) << sh
            if not b & 0x80:
                return n
            sh += 7

    async def check_msg(self):
        """Non-blocking check for incoming messages"""
        # Use select.poll to check if data is available
        poll = select.poll()
        try:
            poll.register(self.sock, select.POLLIN)
            poll_result = poll.poll(0)

            if poll_result:
                # Data available, process it
                return await self.wait_msg()
            else:
                # No data available
                return None
        finally:
            try:
                poll.unregister(self.sock)
            except:
                pass
