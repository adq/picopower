"""
Unit tests for lib.py
Tests syslog functionality
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
import socket


class TestSendSyslog:
    """Test send_syslog function"""

    def test_send_syslog_default_params(self):
        """Test syslog with default parameters"""
        with patch('socket.socket') as mock_socket_class:
            # Mock socket instance
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock

            # Import after patching
            from lib import send_syslog

            # Send a test message
            send_syslog("Test message")

            # Verify socket was created correctly
            mock_socket_class.assert_called_once_with(socket.AF_INET, socket.SOCK_DGRAM)

            # Verify broadcast was enabled
            mock_sock.setsockopt.assert_called_once_with(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

            # Verify message was sent
            assert mock_sock.sendto.call_count == 1
            sent_data, sent_addr = mock_sock.sendto.call_args[0]

            # Verify destination
            assert sent_addr == ('255.255.255.255', 514)

            # Verify message format (syslog RFC 5424)
            sent_msg = sent_data.decode('utf-8')
            assert sent_msg.startswith('<13>1 ')  # Priority 13 (user.notice), version 1
            assert 'picopower' in sent_msg  # hostname
            assert 'main' in sent_msg  # appname
            assert 'Test message' in sent_msg

            # Verify socket was closed
            mock_sock.close.assert_called_once()

    def test_send_syslog_custom_params(self):
        """Test syslog with custom parameters"""
        with patch('socket.socket') as mock_socket_class:
            # Mock socket instance
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock

            # Import after patching
            from lib import send_syslog

            # Send with custom params
            send_syslog(
                "Custom message",
                port=1514,
                hostname="customhost",
                appname="customapp",
                procid="12345",
                msgid="MSG001"
            )

            # Verify custom port was used
            sent_data, sent_addr = mock_sock.sendto.call_args[0]
            assert sent_addr == ('255.255.255.255', 1514)

            # Verify custom fields in message
            sent_msg = sent_data.decode('utf-8')
            assert 'customhost' in sent_msg
            assert 'customapp' in sent_msg
            assert '12345' in sent_msg
            assert 'MSG001' in sent_msg
            assert 'Custom message' in sent_msg

    def test_send_syslog_prints_message(self):
        """Test syslog prints message to console"""
        with patch('socket.socket'), \
             patch('builtins.print') as mock_print:

            # Import after patching
            from lib import send_syslog

            # Send a message
            send_syslog("Print test")

            # Verify message was printed
            mock_print.assert_called_once_with("Print test")

    def test_send_syslog_handles_socket_error(self):
        """Test syslog handles socket send errors gracefully"""
        with patch('socket.socket') as mock_socket_class, \
             patch('builtins.print') as mock_print:

            # Mock socket that fails to send
            mock_sock = MagicMock()
            mock_sock.sendto.side_effect = OSError("Network unreachable")
            mock_socket_class.return_value = mock_sock

            # Import after patching
            from lib import send_syslog

            # Send a message (should not raise exception)
            send_syslog("Error test")

            # Verify error was printed
            assert any("Syslog send failed" in str(call) for call in mock_print.call_args_list)

            # Verify socket was still closed
            mock_sock.close.assert_called_once()

    def test_send_syslog_closes_socket_on_exception(self):
        """Test syslog closes socket even if exception occurs"""
        with patch('socket.socket') as mock_socket_class:

            # Mock socket that raises exception
            mock_sock = MagicMock()
            mock_sock.sendto.side_effect = Exception("Unexpected error")
            mock_socket_class.return_value = mock_sock

            # Import after patching
            from lib import send_syslog

            # Send a message (should not raise exception)
            send_syslog("Exception test")

            # Verify socket was closed despite exception
            mock_sock.close.assert_called_once()

    def test_send_syslog_message_format(self):
        """Test syslog message follows RFC 5424 format"""
        with patch('socket.socket') as mock_socket_class:
            # Mock socket instance
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock

            # Import after patching
            from lib import send_syslog

            # Send a message
            send_syslog(
                "Format test",
                hostname="testhost",
                appname="testapp",
                procid="999",
                msgid="TEST"
            )

            # Get sent message
            sent_data, _ = mock_sock.sendto.call_args[0]
            sent_msg = sent_data.decode('utf-8')

            # Verify RFC 5424 format: <PRI>VERSION HOSTNAME APP-NAME PROCID MSGID STRUCTURED-DATA MSG
            parts = sent_msg.split(' ', 6)
            assert parts[0] == '<13>1'  # Priority and version
            assert parts[1] == 'testhost'  # Hostname
            assert parts[2] == 'testapp'  # App name
            assert parts[3] == '999'  # Process ID
            assert parts[4] == 'TEST'  # Message ID
            assert parts[5] == '-'  # Structured data (none)
            assert parts[6] == 'Format test\r\n'  # Message

    def test_send_syslog_priority_encoding(self):
        """Test syslog priority is correctly encoded"""
        with patch('socket.socket') as mock_socket_class:
            # Mock socket instance
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock

            # Import after patching
            from lib import send_syslog

            # Send a message
            send_syslog("Priority test")

            # Get sent message
            sent_data, _ = mock_sock.sendto.call_args[0]
            sent_msg = sent_data.decode('utf-8')

            # Priority 13 = Facility 1 (user) * 8 + Severity 5 (notice)
            assert sent_msg.startswith('<13>')

    def test_send_syslog_special_characters(self):
        """Test syslog handles special characters in message"""
        with patch('socket.socket') as mock_socket_class:
            # Mock socket instance
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock

            # Import after patching
            from lib import send_syslog

            # Send message with special characters
            special_msg = "Test: ñ, 中文, emoji 🔥, quotes \"test\""
            send_syslog(special_msg)

            # Verify message was sent (should encode to UTF-8)
            assert mock_sock.sendto.call_count == 1
            sent_data, _ = mock_sock.sendto.call_args[0]

            # Verify it's valid UTF-8
            decoded_msg = sent_data.decode('utf-8')
            assert special_msg in decoded_msg
