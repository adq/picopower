"""Tests for async_mqtt_client.py"""

import unittest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import struct

from async_mqtt_client import AsyncMQTTClient, MQTTException


class TestAsyncMQTTClientInit(unittest.TestCase):
    """Test AsyncMQTTClient initialization"""

    def test_init_minimal(self):
        client = AsyncMQTTClient("test_client", "localhost")
        self.assertEqual(client.client_id, b"test_client")
        self.assertEqual(client.server, "localhost")
        self.assertEqual(client.port, 1883)
        self.assertFalse(client.ssl)
        self.assertIsNone(client.user)
        self.assertIsNone(client.pswd)
        self.assertEqual(client.keepalive, 0)

    def test_init_with_ssl(self):
        client = AsyncMQTTClient("test_client", "localhost", ssl=True)
        self.assertEqual(client.port, 8883)
        self.assertTrue(client.ssl)

    def test_init_with_custom_port(self):
        client = AsyncMQTTClient("test_client", "localhost", port=1234)
        self.assertEqual(client.port, 1234)

    def test_init_with_auth(self):
        client = AsyncMQTTClient("test_client", "localhost", user="testuser", password="testpass")
        self.assertEqual(client.user, b"testuser")
        self.assertEqual(client.pswd, b"testpass")

    def test_init_with_keepalive(self):
        client = AsyncMQTTClient("test_client", "localhost", keepalive=60)
        self.assertEqual(client.keepalive, 60)


class TestAsyncMQTTClientSetters(unittest.TestCase):
    """Test AsyncMQTTClient setter methods"""

    def test_set_callback(self):
        client = AsyncMQTTClient("test_client", "localhost")
        callback = lambda topic, msg: None
        client.set_callback(callback)
        self.assertEqual(client.cb, callback)

    def test_set_last_will_valid(self):
        client = AsyncMQTTClient("test_client", "localhost")
        client.set_last_will("test/topic", b"offline", retain=True, qos=1)
        self.assertEqual(client.lw_topic, b"test/topic")
        self.assertEqual(client.lw_msg, b"offline")
        self.assertTrue(client.lw_retain)
        self.assertEqual(client.lw_qos, 1)

    def test_set_last_will_invalid_qos(self):
        client = AsyncMQTTClient("test_client", "localhost")
        with self.assertRaises(ValueError) as ctx:
            client.set_last_will("test/topic", b"offline", qos=3)
        self.assertIn("Invalid QoS", str(ctx.exception))

    def test_set_last_will_empty_topic(self):
        client = AsyncMQTTClient("test_client", "localhost")
        with self.assertRaises(ValueError) as ctx:
            client.set_last_will("", b"offline")
        self.assertIn("Topic cannot be empty", str(ctx.exception))

    def test_set_last_will_non_bytes_msg(self):
        client = AsyncMQTTClient("test_client", "localhost")
        with self.assertRaises(TypeError) as ctx:
            client.set_last_will("test/topic", "offline")
        self.assertIn("msg must be bytes", str(ctx.exception))


class TestAsyncMQTTClientPublish(unittest.IsolatedAsyncioTestCase):
    """Test AsyncMQTTClient publish methods"""

    async def test_publish_requires_bytes(self):
        client = AsyncMQTTClient("test_client", "localhost")
        # Setup mock writer
        client._writer = MagicMock()
        client._writer.write = MagicMock()
        client._writer.drain = AsyncMock()

        # Should raise TypeError for string payload
        with self.assertRaises(TypeError) as ctx:
            await client.publish("test/topic", "test message")
        self.assertIn("msg must be bytes", str(ctx.exception))

    async def test_publish_bytes_valid(self):
        client = AsyncMQTTClient("test_client", "localhost")
        # Setup mock writer
        client._writer = MagicMock()
        client._writer.write = MagicMock()
        client._writer.drain = AsyncMock()

        # Should work with bytes payload
        await client.publish("test/topic", b"test message", qos=0)
        self.assertTrue(client._writer.write.called)
        self.assertTrue(client._writer.drain.called)

    async def test_publish_string_convenience_method(self):
        client = AsyncMQTTClient("test_client", "localhost")
        # Setup mock writer
        client._writer = MagicMock()
        client._writer.write = MagicMock()
        client._writer.drain = AsyncMock()

        # publish_string should handle string encoding
        await client.publish_string("test/topic", "test message")
        self.assertTrue(client._writer.write.called)
        self.assertTrue(client._writer.drain.called)

    async def test_publish_message_too_long(self):
        client = AsyncMQTTClient("test_client", "localhost")
        client._writer = MagicMock()

        # Message exceeding 2MB limit
        huge_msg = b"x" * 2097152
        with self.assertRaises(MQTTException) as ctx:
            await client.publish("test/topic", huge_msg)
        self.assertIn("Message too long", str(ctx.exception))


class TestAsyncMQTTClientSubscribe(unittest.IsolatedAsyncioTestCase):
    """Test AsyncMQTTClient subscribe method"""

    async def test_subscribe_without_callback_raises(self):
        client = AsyncMQTTClient("test_client", "localhost")
        client._writer = MagicMock()
        client._reader = AsyncMock()

        with self.assertRaises(MQTTException) as ctx:
            await client.subscribe("test/topic")
        self.assertIn("Callback not set", str(ctx.exception))

    async def test_subscribe_with_callback(self):
        client = AsyncMQTTClient("test_client", "localhost")
        client.set_callback(lambda topic, msg: None)

        # Setup mocks
        client._writer = MagicMock()
        client._writer.write = MagicMock()
        client._writer.drain = AsyncMock()
        client._reader = AsyncMock()

        # Mock _wait_msg_internal to return SUBACK
        async def mock_wait_msg():
            return 0x90  # SUBACK
        client._wait_msg_internal = mock_wait_msg

        # Mock readexactly for SUBACK response
        client._reader.readexactly = AsyncMock(return_value=b"\x00\x00\x00\x00")

        await client.subscribe("test/topic", qos=0)
        self.assertTrue(client._writer.write.called)
        self.assertTrue(client._writer.drain.called)


class TestAsyncMQTTClientCallback(unittest.IsolatedAsyncioTestCase):
    """Test MQTT callback handling"""

    async def test_wait_msg_calls_callback(self):
        client = AsyncMQTTClient("test_client", "localhost")

        # Track callback invocations
        received = []
        def test_callback(topic, msg):
            received.append((topic, msg))

        client.set_callback(test_callback)

        # Mock reader to return PUBLISH packet
        client._reader = AsyncMock()
        client._writer = MagicMock()
        client._writer.write = MagicMock()
        client._writer.drain = AsyncMock()

        # Simulate PUBLISH packet: topic "test/topic", message b"hello"
        topic_bytes = b"test/topic"
        msg_bytes = b"hello"

        # PUBLISH packet structure: [opcode, remaining_length, topic_len_msb, topic_len_lsb, topic, message]
        async def mock_readexactly(n):
            if n == 1:
                return b"\x30"  # PUBLISH with QoS 0
            elif n == 2:
                return struct.pack("!H", len(topic_bytes))
            elif n == len(topic_bytes):
                return topic_bytes
            elif n == len(msg_bytes):
                return msg_bytes
            else:
                return b"\x00" * n

        client._reader.readexactly = mock_readexactly

        # Mock _recv_len to return message size
        async def mock_recv_len():
            return 2 + len(topic_bytes) + len(msg_bytes)
        client._recv_len = mock_recv_len

        await client.wait_msg()

        # Check callback was called with decoded topic and raw message bytes
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0], ("test/topic", b"hello"))


class TestAsyncMQTTClientPing(unittest.IsolatedAsyncioTestCase):
    """Test ping functionality"""

    async def test_ping_sends_pingreq(self):
        client = AsyncMQTTClient("test_client", "localhost")
        client._writer = MagicMock()
        client._writer.write = MagicMock()
        client._writer.drain = AsyncMock()

        await client.ping()

        # Check PINGREQ packet was written
        client._writer.write.assert_called_with(b"\xc0\0")
        self.assertTrue(client._writer.drain.called)

    async def test_wait_msg_handles_pingresp(self):
        client = AsyncMQTTClient("test_client", "localhost")
        client._reader = AsyncMock()

        # Simulate PINGRESP packet
        async def mock_readexactly(n):
            if n == 1:
                if not hasattr(mock_readexactly, 'called'):
                    mock_readexactly.called = True
                    return b"\xd0"  # PINGRESP
                return b"\x00"
            return b"\x00"

        client._reader.readexactly = mock_readexactly

        result = await client.wait_msg()
        self.assertIsNone(result)


class TestAsyncMQTTClientDisconnect(unittest.IsolatedAsyncioTestCase):
    """Test disconnect functionality"""

    async def test_disconnect_sends_disconnect_packet(self):
        client = AsyncMQTTClient("test_client", "localhost")
        mock_writer = MagicMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_sock = MagicMock()
        mock_sock.close = MagicMock()

        client._writer = mock_writer
        client.sock = mock_sock

        await client.disconnect()

        # Check DISCONNECT packet was written before cleanup
        mock_writer.write.assert_called_with(b"\xe0\0")
        self.assertTrue(mock_writer.drain.called)
        self.assertTrue(mock_sock.close.called)

        # Check cleanup happened
        self.assertIsNone(client._writer)
        self.assertIsNone(client._reader)
        self.assertIsNone(client.sock)

    async def test_disconnect_cleans_up_on_error(self):
        client = AsyncMQTTClient("test_client", "localhost")
        mock_writer = MagicMock()
        mock_writer.write = MagicMock(side_effect=Exception("Write failed"))
        mock_writer.drain = AsyncMock()
        mock_sock = MagicMock()
        mock_sock.close = MagicMock()

        client._writer = mock_writer
        client.sock = mock_sock

        # Should clean up even if write fails - but will raise
        try:
            await client.disconnect()
        except Exception:
            pass  # Expected

        # Check cleanup happened even on error
        self.assertTrue(mock_sock.close.called)
        self.assertIsNone(client._writer)
        self.assertIsNone(client.sock)


if __name__ == '__main__':
    unittest.main()
