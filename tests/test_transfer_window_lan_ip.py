# -*- coding: utf-8 -*-
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "transfer_window_app"))

from main import _collect_lan_ips, _lan_ip_priority


def test_lan_ip_priority_prefers_home_wifi():
    assert _lan_ip_priority("192.168.1.124") < _lan_ip_priority("172.31.125.158")


def test_collect_lan_ips_skips_utun(monkeypatch):
    fake_ifconfig = """
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
	inet 192.168.1.124 netmask 0xffffff00 broadcast 192.168.1.255
utun4: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1380
	inet 172.31.125.158 --> 172.31.125.158 netmask 0xffffffc0
lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384
	inet 127.0.0.1 netmask 0xff000000
"""
    with patch("subprocess.check_output", return_value=fake_ifconfig):
        ips = _collect_lan_ips()
    assert ips[0] == "192.168.1.124"
    assert "172.31.125.158" not in ips
