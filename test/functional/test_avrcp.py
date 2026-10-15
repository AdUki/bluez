# -*- coding: utf-8; mode: python; eval: (blacken-mode); -*-
# SPDX-License-Identifier: LGPL-2.1-or-later
import uuid
import threading
import time
import select
import os
import subprocess
import struct
import socket

import pytest
import dbus

from pytest_bluezenv import (
    host_config,
    Bluetoothd,
    Agent,
    wait_until,
    mainloop_wrap,
    get_dbus,
    HostPlugin,
    EventPluginMixin,
    dbus_service_event_method,
)


class CheckAvrcpCrash_GHSA_m2vx_pw5f_rc8v(HostPlugin):
    name = "avrcp_crash"

    @mainloop_wrap
    def setup(self, impl):
        self.bus = get_dbus()
        self.profile = check_avrcp_GHSA_m2vx_pw5f_rc8v(self.bus)
        print("[*] waiting for victim AVRCP connection", flush=True)

    def wait_done(self):
        return self.profile.wait_done()


@host_config(
    [Agent()],
    [
        Bluetoothd(args=("-d", "-P", "avrcp")),
        CheckAvrcpCrash_GHSA_m2vx_pw5f_rc8v(),
        Agent(),
    ],
)
def test_avrcp_GHSA_m2vx_pw5f_rc8v(paired_hosts):
    client, server = paired_hosts

    client.agent.device_method(
        server.bdaddr, "ConnectProfile", "0000110c-0000-1000-8000-00805f9b34fb"
    )
    client.agent.expect("org.bluez.Device1.ConnectProfile:reply")

    assert server.avrcp_crash.wait_done()

    # Bluetoothd shall not have crashed, and still respond
    client.agent.device_method(server.bdaddr, "Disconnect")
    client.agent.expect("org.bluez.Device1.Disconnect:reply")


def check_avrcp_GHSA_m2vx_pw5f_rc8v(bus):
    """NN-2026-0145 AVRCP PoC. BlueZ supplies the accepted AVCTP file
    descriptor through Profile1.NewConnection.

    """

    PSM_AVCTP = 0x17
    AVC_PID = 0x110E
    AVCTP_COMMAND = 0
    AVCTP_RESPONSE = 1
    AVC_CTYPE_ACCEPTED = 0x09
    AVC_CTYPE_STABLE = 0x0C
    AVC_CTYPE_INTERIM = 0x0F
    AVC_OP_VENDORDEP = 0x00
    AVC_SUBUNIT_PANEL = 0x09

    PDU_GET_CAPABILITIES = 0x10
    PDU_LIST_PLAYER_ATTRS = 0x11
    PDU_GET_CURRENT_PLAYER_VALUE = 0x13
    PDU_REGISTER_NOTIFICATION = 0x31
    CAP_EVENTS_SUPPORTED = 0x03
    EVENT_TRACK_CHANGED = 0x02
    COMPANY_BTSIG = b"\x00\x19\x58"

    SDP_TG_RECORD = """<?xml version="1.0" encoding="UTF-8" ?>
    <record>
      <attribute id="0x0001">
        <sequence><uuid value="0x110c"/><uuid value="0x110e"/></sequence>
      </attribute>
      <attribute id="0x0004">
        <sequence>
          <sequence><uuid value="0x0100"/><uint16 value="0x0017"/></sequence>
          <sequence><uuid value="0x0017"/><uint16 value="0x0104"/></sequence>
        </sequence>
      </attribute>
      <attribute id="0x0009">
        <sequence><sequence><uuid value="0x110e"/><uint16 value="0x0104"/></sequence></sequence>
      </attribute>
      <attribute id="0x0311"><uint16 value="0x0011"/></attribute>
    </record>
    """

    def hexdump(data):
        if data is None:
            return "<None>"
        return " ".join("%02x" % byte for byte in data)

    def send_all(fd, data):
        view = memoryview(data)
        while view:
            count = os.write(fd, view)
            if count <= 0:
                raise OSError("AVCTP write made no progress")
            view = view[count:]

    def recv_one(fd):
        readable, _, _ = select.select([fd], [], [], None)
        if readable:
            try:
                return os.read(fd, 1024)
            except OSError:
                return None
        return None

    def avctp_header(transaction, command_response):
        return bytes([(transaction << 4) | (command_response << 1)]) + struct.pack(
            ">H", AVC_PID
        )

    def avc_frame(ctype, payload):
        return bytes([ctype & 0x0F, AVC_SUBUNIT_PANEL << 3, AVC_OP_VENDORDEP]) + payload

    def avrcp_pdu(pdu_id, params, packet_type=0):
        return (
            COMPANY_BTSIG
            + bytes([pdu_id, packet_type])
            + struct.pack(">H", len(params))
            + params
        )

    def parse_avctp(data):
        if len(data) < 3:
            return None
        return (data[0] >> 4, (data[0] >> 1) & 1, data[3:])

    def parse_vendor(payload):
        if len(payload) < 10 or payload[2] != AVC_OP_VENDORDEP:
            return None
        pdu_id = payload[6]
        length = struct.unpack(">H", payload[8:10])[0]
        return payload[0] & 0x0F, pdu_id, payload[10 : 10 + length]

    class AvrcpTarget:
        def __init__(self):
            self.fd = -1
            self.event = threading.Event()

        def response(self, transaction, ctype, pdu):
            frame = avctp_header(transaction, AVCTP_RESPONSE) + avc_frame(ctype, pdu)
            print("-> " + hexdump(frame), flush=True)
            send_all(self.fd, frame)

        def loop(self):
            while self.fd >= 0:
                data = recv_one(self.fd)
                if data == b"":
                    print("[*] peer closed AVCTP", flush=True)
                    return

                print("<- " + hexdump(data), flush=True)
                header = parse_avctp(data)
                if not header:
                    continue
                transaction, command_response, payload = header
                if command_response != AVCTP_COMMAND:
                    continue

                vendor = parse_vendor(payload)
                if not vendor:
                    send_all(
                        self.fd,
                        avctp_header(transaction, AVCTP_RESPONSE)
                        + bytes([AVC_CTYPE_ACCEPTED])
                        + payload[1:],
                    )
                    continue

                _, pdu_id, params = vendor
                if pdu_id == PDU_GET_CAPABILITIES:
                    caps = bytes([CAP_EVENTS_SUPPORTED, 1, EVENT_TRACK_CHANGED])
                    self.response(
                        transaction,
                        AVC_CTYPE_STABLE,
                        avrcp_pdu(PDU_GET_CAPABILITIES, caps),
                    )
                elif pdu_id == PDU_LIST_PLAYER_ATTRS:
                    evil = bytes([0xFF]) + bytes(
                        (index % 4) + 1 for index in range(255)
                    )
                    print(
                        "[+] answering ListPlayerAttributes with count=255", flush=True
                    )
                    self.response(
                        transaction,
                        AVC_CTYPE_STABLE,
                        avrcp_pdu(PDU_LIST_PLAYER_ATTRS, evil),
                    )

                    self.event.set()
                elif pdu_id == PDU_GET_CURRENT_PLAYER_VALUE:
                    print(
                        "[+] received current-player-value data: %s" % hexdump(params),
                        flush=True,
                    )
                elif pdu_id == PDU_REGISTER_NOTIFICATION:
                    print("[*] RegisterNotification: %s" % hexdump(params), flush=True)

                    # Answer as a target would, otherwise the request
                    # times out and is retried, and the controller only
                    # moves on to the next one 20 seconds later
                    self.response(
                        transaction,
                        AVC_CTYPE_INTERIM,
                        avrcp_pdu(
                            PDU_REGISTER_NOTIFICATION,
                            bytes([EVENT_TRACK_CHANGED]) + bytes(8),
                        ),
                    )
                else:
                    self.response(transaction, 0x0A, avrcp_pdu(pdu_id, b"\x00"))

    class Profile(dbus.service.Object):
        def __init__(self, bus, path, target):
            super().__init__(bus, path)
            self.target = target
            self.fd = -1

        @dbus.service.method("org.bluez.Profile1", in_signature="", out_signature="")
        def Release(self):
            self.close()

        @dbus.service.method("org.bluez.Profile1", in_signature="", out_signature="")
        def Cancel(self):
            pass

        @dbus.service.method(
            "org.bluez.Profile1", in_signature="oha{sv}", out_signature=""
        )
        def NewConnection(self, device, fd, properties):
            self.close()
            self.fd = fd.take()
            os.set_blocking(self.fd, True)
            self.target.fd = self.fd
            print("[+] AVRCP connection from %s" % device, flush=True)
            threading.Thread(target=self.target.loop, daemon=True).start()

        @dbus.service.method("org.bluez.Profile1", in_signature="o", out_signature="")
        def RequestDisconnection(self, device):
            self.close()

        def wait_done(self):
            return self.target.event.wait()

        def close(self):
            if self.fd >= 0:
                try:
                    os.close(self.fd)
                except OSError:
                    pass
                self.fd = -1
                self.target.fd = -1

    def register_profile(bus, target):
        profile = Profile(bus, "/bluez_poc/nn20260145", target)
        manager = dbus.Interface(
            bus.get_object("org.bluez", "/org/bluez"), "org.bluez.ProfileManager1"
        )
        options = {
            "ServiceRecord": dbus.String(SDP_TG_RECORD),
            "Role": dbus.String("server"),
            "PSM": dbus.UInt16(PSM_AVCTP),
            "RequireAuthentication": dbus.Boolean(False),
            "RequireAuthorization": dbus.Boolean(False),
        }
        manager.RegisterProfile(
            dbus.ObjectPath("/bluez_poc/nn20260145"),
            dbus.String(str(uuid.uuid4())),
            options,
        )
        print("[+] AVRCP Target profile registered on PSM 0x17", flush=True)
        return profile

    target = AvrcpTarget()
    return register_profile(bus, target)


@mainloop_wrap
def set_trusted(bdaddr):
    path = "/org/bluez/hci0/dev_" + bdaddr.upper().replace(":", "_")
    props = dbus.Interface(
        get_dbus().get_object("org.bluez", path), "org.freedesktop.DBus.Properties"
    )
    props.Set("org.bluez.Device1", "Trusted", dbus.Boolean(True))


SOL_L2CAP = 6
L2CAP_OPTIONS = 0x01
L2CAP_OPTIONS_FMT = "=HHHBBBxH"
L2CAP_MODE_ERTM = 0x03

AVCTP_CONTROL_PSM = 0x17
AVCTP_BROWSING_PSM = 0x1B
AV_REMOTE_PID = 0x110E

AVRCP_GET_FOLDER_ITEMS = 0x71
AVRCP_STATUS_INVALID_PARAM = 0x01
AVRCP_STATUS_OUT_OF_BOUNDS = 0x0B


def l2cap_connect(bdaddr, psm, mode=None):
    sock = socket.socket(
        socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP
    )

    if mode is not None:
        size = struct.calcsize(L2CAP_OPTIONS_FMT)
        opts = list(
            struct.unpack(
                L2CAP_OPTIONS_FMT, sock.getsockopt(SOL_L2CAP, L2CAP_OPTIONS, size)
            )
        )
        opts[3] = mode
        sock.setsockopt(SOL_L2CAP, L2CAP_OPTIONS, struct.pack(L2CAP_OPTIONS_FMT, *opts))

    sock.settimeout(10)
    sock.connect((bdaddr, psm))
    return sock


def avrcp_browsing_commands(bdaddr, commands):
    """
    Connect the AVCTP control and browsing channels, and send the AVRCP
    browsing commands, given as (pdu_id, parameter length, parameters).

    Returns the parameters of the responses.
    """
    # The browsing channel is only accepted once the control one is connected
    control = l2cap_connect(bdaddr, AVCTP_CONTROL_PSM)
    browsing = l2cap_connect(bdaddr, AVCTP_BROWSING_PSM, L2CAP_MODE_ERTM)
    responses = []

    for transaction, (pdu_id, param_len, params) in enumerate(commands):
        browsing.send(
            bytes([transaction << 4])
            + struct.pack(">HBH", AV_REMOTE_PID, pdu_id, param_len)
            + params
        )

        rsp = browsing.recv(1024)
        assert rsp[0] == (transaction << 4) | 0x02, f"response: {rsp.hex()}"
        assert rsp[3] == pdu_id, f"response: {rsp.hex()}"
        responses.append(rsp[6:])

    browsing.close()
    control.close()

    return responses


@host_config(
    [Bluetoothd(args=("-P", "avrcp")), Agent()],
    [Agent()],
)
def test_avrcp_browsing_parameter_length(paired_hosts):
    host0, host1 = paired_hosts

    host1.call(set_trusted, host0.bdaddr)

    # Media player list, from item 0 to 0, without attributes
    params = bytes(10)

    short, valid = host0.call(
        avrcp_browsing_commands,
        host1.bdaddr,
        [
            (AVRCP_GET_FOLDER_ITEMS, len(params), b""),
            (AVRCP_GET_FOLDER_ITEMS, len(params), params),
        ],
    )

    assert short == bytes([AVRCP_STATUS_INVALID_PARAM]), short.hex()

    # host1 has no media player
    assert valid == bytes([AVRCP_STATUS_OUT_OF_BOUNDS]), valid.hex()


AVRCP_TARGET_UUID = "0000110c-0000-1000-8000-00805f9b34fb"

MEDIA_PLAYER_INTERFACE = "org.bluez.MediaPlayer1"
MEDIA_FOLDER_INTERFACE = "org.bluez.MediaFolder1"
MEDIA_ITEM_INTERFACE = "org.bluez.MediaItem1"

TG_PLAYER_NAME = "Browsable Player"
TG_PLAYER = "/org/bluez/test/player"
TG_FOLDER = TG_PLAYER + "/music"
TG_TRACK = TG_FOLDER + "/track"

# The content of each folder, the player object being the root folder
TG_FOLDERS = {
    TG_PLAYER: {TG_FOLDER: {"Name": "Music", "Type": "folder", "Playable": False}},
    TG_FOLDER: {TG_TRACK: {"Name": "Track", "Type": "audio", "Playable": True}},
}


class TgPlayer(dbus.service.Object):
    """Player object of the browsable player, and its root folder."""

    def __init__(self, bus):
        self.folder = TG_PLAYER
        super().__init__(bus, TG_PLAYER)

    @dbus.service.method(MEDIA_FOLDER_INTERFACE, in_signature="o", out_signature="")
    def ChangeFolder(self, folder):
        self.folder = str(folder)

    @dbus.service.method(
        MEDIA_FOLDER_INTERFACE, in_signature="a{sv}", out_signature="a{oa{sv}}"
    )
    def ListItems(self, filters):
        return TG_FOLDERS[self.folder]

    @dbus.service.method(
        "org.freedesktop.DBus.Properties", in_signature="ss", out_signature="v"
    )
    def Get(self, interface, name):
        # NumberOfItems of org.bluez.MediaFolder1
        return dbus.UInt32(len(TG_FOLDERS[self.folder]))


class TgTrack(dbus.service.Object):
    def __init__(self, bus, events):
        self.events = events
        super().__init__(bus, TG_TRACK)

    Play = dbus_service_event_method(MEDIA_ITEM_INTERFACE, "Play")


class BrowsablePlayer(HostPlugin, EventPluginMixin):
    """
    Host plugin registering a browsable local player with
    org.bluez.Media1.RegisterPlayer: a root folder holding a folder with
    one track. Play of the track is pushed as an org.bluez.MediaItem1.Play
    event.
    """

    name = "browsable_player"
    depends = [Bluetoothd()]

    @mainloop_wrap
    def setup(self, impl):
        EventPluginMixin.setup(self, impl)

        bus = get_dbus()
        self.objects = [TgPlayer(bus), TgTrack(bus, self.events)]

        media = dbus.Interface(
            bus.get_object("org.bluez", "/org/bluez/hci0"), "org.bluez.Media1"
        )
        props = {
            "Identity": dbus.String(TG_PLAYER_NAME),
            "Browsable": dbus.Boolean(True),
        }
        media.RegisterPlayer(
            dbus.ObjectPath(TG_PLAYER), dbus.Dictionary(props, signature="sv")
        )

    @mainloop_wrap
    def teardown(self):
        for obj in self.objects:
            obj.remove_from_connection()


def bluez_interface(path, interface):
    return dbus.Interface(get_dbus().get_object("org.bluez", path), interface)


@mainloop_wrap
def find_browsable_player():
    """Return the path and the name of the remote player, once browsable."""
    manager = bluez_interface("/", "org.freedesktop.DBus.ObjectManager")

    for path, interfaces in manager.GetManagedObjects().items():
        props = interfaces.get(MEDIA_PLAYER_INTERFACE, {})
        if props.get("Browsable") and MEDIA_FOLDER_INTERFACE in interfaces:
            return str(path), str(props["Name"])

    return None


@mainloop_wrap
def list_items(player):
    """List the current folder of the player, as {name: path}."""
    folder = bluez_interface(player, MEDIA_FOLDER_INTERFACE)
    items = folder.ListItems(dbus.Dictionary({}, signature="sv"))
    return {str(props["Name"]): str(path) for path, props in items.items()}


@mainloop_wrap
def change_folder(player, path):
    folder = bluez_interface(player, MEDIA_FOLDER_INTERFACE)
    folder.ChangeFolder(dbus.ObjectPath(path))


@mainloop_wrap
def play_item(path):
    bluez_interface(path, MEDIA_ITEM_INTERFACE).Play()


@host_config(
    [Agent()],
    [BrowsablePlayer(), Agent()],
)
def test_avrcp_tg_browse(paired_hosts):
    host0, host1 = paired_hosts

    host1.call(set_trusted, host0.bdaddr)
    host0.agent.device_method(host1.bdaddr, "ConnectProfile", AVRCP_TARGET_UUID)
    host0.agent.expect("org.bluez.Device1.ConnectProfile:reply")

    wait_until(lambda: host0.call(find_browsable_player))
    player, name = host0.call(find_browsable_player)
    assert name == TG_PLAYER_NAME

    # The controller names a folder with its path
    items = host0.call(list_items, player)
    assert list(items) == ["/Filesystem/Music"]

    host0.call(change_folder, player, items["/Filesystem/Music"])
    items = host0.call(list_items, player)
    assert list(items) == ["Track"]

    host0.call(play_item, items["Track"])
    host1.browsable_player.expect(f"{MEDIA_ITEM_INTERFACE}.Play")
