================
functional-avrcp
================

DESCRIPTION
===========

AVRCP functional tests, `test/functional/test_avrcp.py`. See
**functional-testing(7)** for the conventions used here, and
**test-functional(1)** for how to run the suite.

SETUP
=====

Two hosts, connected over BR/EDR:

.. code-block::

	+------------------------+                 +------------------------+
	| host0                  |     BR/EDR      | host1                  |
	| victim                 | --------------> | attacker               |
	| bluetoothd             |                 | bluetoothd -P avrcp    |
	| AVRCP Controller       |  AVCTP PSM 0x17 | malicious AVRCP Target |
	|                        | <============== | (org.bluez.Profile1)   |
	+------------------------+                 +------------------------+

	--> connection is initiated by      ==> malicious response is sent by

TEST CASES
==========

test_avrcp_GHSA_m2vx_pw5f_rc8v
------------------------------

:Setup: Two hosts paired over BR/EDR. host1 runs `bluetoothd` with the
	`avrcp` plugin and registers a malicious AVRCP Target through
	``org.bluez.ProfileManager1``: a server role profile on the AVCTP
	PSM (0x17) with its own SDP record, which receives the accepted
	AVCTP file descriptor through ``Profile1.NewConnection``.

:Steps:
	1. host0 connects the AVRCP Controller UUID
	   (``0000110c-0000-1000-8000-00805f9b34fb``) with
	   ``org.bluez.Device1.ConnectProfile``.
	2. The AVRCP Target answers ``GetCapabilities``, and answers
	   ``ListPlayerAttributes`` with an attribute count of 255.
	3. host0 calls ``org.bluez.Device1.Disconnect``.

:Expected:
	1. ``ConnectProfile`` replies.
	2. The target reports that it answered
	   ``ListPlayerAttributes``.
	3. `bluetoothd` on host0 has not crashed and still answers D-Bus,
	   so ``Disconnect`` replies.

:Notes: Regression test for NN-2026-0145. The response is parsed by
	``avrcp_list_player_attributes_rsp()``
	(`profiles/audio/avrcp.c`), which collects the attributes into a
	buffer of ``AVRCP_ATTRIBUTE_LAST`` bytes without bounding the
	count, and then passes that count to
	``avrcp_get_current_player_value()``, which copies it into a
	similarly sized buffer. With 255 valid attributes both overflow.

	Marked ``sa``.

test_avrcp_browsing_parameter_length
------------------------------------

:Setup: Two hosts paired over BR/EDR. host0 runs `bluetoothd` without
	the `avrcp` plugin and drives AVCTP from the test over L2CAP
	sockets. host1 runs `bluetoothd`, with no media player
	registered, and trusts host0.

	.. code-block::

		+--------------------------+                 +--------------------------+
		| host0                    |     BR/EDR      | host1                    |
		| bluetoothd -P avrcp      | --------------> | bluetoothd               |
		| raw AVRCP Controller     |  AVCTP PSM 0x17 | AVRCP Target             |
		| (L2CAP sockets)          |  and PSM 0x1b   |                          |
		|                          | <============== |                          |
		+--------------------------+                 +--------------------------+

:Steps:
	1. host0 connects the AVCTP control channel, then the browsing
	   channel (Enhanced Retransmission Mode).
	2. host0 sends a ``GetFolderItems`` with a parameter length of 10
	   but no parameters.
	3. host0 sends a ``GetFolderItems`` of the media player list, from
	   item 0 to 0, with its 10 bytes of parameters.

:Expected:
	1. The first ``GetFolderItems`` is answered with status Invalid
	   Parameter.
	2. The second one is answered with status Range Out of Bounds, as
	   host1 has no media player.

:Notes: The parameter length of a browsing PDU was not checked against
	the bytes received, so the target took the missing parameters from
	what its receive buffer held before, here zeroes, and answered the
	first command as the second one.

test_avrcp_tg_browse
--------------------

:Setup: Two hosts paired over BR/EDR, each running `bluetoothd`. host1
	trusts host0, and registers a browsable local player with
	``org.bluez.Media1.RegisterPlayer``: its player object is the root
	folder (``org.bluez.MediaFolder1``), holding a folder "Music" with
	a track "Track" (``org.bluez.MediaItem1``).

	.. code-block::

		+--------------------------+                 +--------------------------+
		| host0                    |     BR/EDR      | host1                    |
		| bluetoothd               | --------------> | bluetoothd               |
		| AVRCP Controller         |  AVCTP control  | AVRCP Target             |
		| org.bluez.MediaPlayer1   |  and browsing   | browsable local player   |
		|                          | <============== |                          |
		+--------------------------+                 +--------------------------+

:Steps:
	1. host0 connects the AVRCP Target UUID
	   (``0000110c-0000-1000-8000-00805f9b34fb``) with
	   ``org.bluez.Device1.ConnectProfile``.
	2. Wait until host0 has a ``Browsable`` player implementing
	   ``org.bluez.MediaFolder1``.
	3. host0 lists its root folder with ``ListItems``.
	4. host0 changes to the folder listed with ``ChangeFolder``, and
	   lists it.
	5. host0 calls ``org.bluez.MediaItem1.Play`` on the track listed.

:Expected:
	1. The player of host0 has the name of the player of host1.
	2. The root folder lists the folder, as "/Filesystem/Music".
	3. The folder lists "Track".
	4. ``Play`` is called on the track of host1.
