#This file was created by Yombo for use with Yombo Python Gateway automation
#software.  Details can be found at https://yombo.net
"""
Insteon PLM
===========

Provides support for Insteon devices.

License
=======

This module is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 1 of the License, or
(at your option) any later version.

The **`Yombo.net <http://www.yombo.net/>`_** team and other contributors
hopes that it will be useful, but WITHOUT ANY WARRANTY; without even the
implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU General Public License for more details.

The GNU General Public License can be found here: `GNU.Org <http://www.gnu.org/licenses>`_

Implements
==========
- InsteonPLM

.. moduleauthor:: Mitch Schwenk <mitch-gw@yombo.net>
:copyright: Copyright 2012-2017 by Yombo.
:license: GPL(v1)
:organization: `Yombo <https://yombo.net>`_
"""
from collections import deque

from twisted.internet import reactor
from twisted.internet.defer import ensureDeferred, inlineCallbacks, Deferred, DeferredList

from yombo.core.module import YomboModule
from yombo.core.log import get_logger
from yombo.utils import translate_int_value

from yombo.modules.insteonplm import plm
from yombo.modules.insteonplm.plm.plm import Address, PLMProtocol, Message

logger = get_logger("modules.insteonplm")


class InsteonPLM(YomboModule):
    """
    The primary class...
    """

    _insteon_commands = {
        0x11: 'on',
        0x12: 'on_fast',
        0x13: 'off',
        0x14: 'off_fast',
    }

    _insteon_commands_lookup = {
        'on': {
            'insteon': 0x11,
            'x10': 0x02,
        },
        'faston': {
            'insteon': 0x12,
            'x10': 0x02,
        },
        'off': {
            'insteon': 0x13,
            'x10': 0x03,
        },
        'fastoff':{
            'insteon': 0x14,
            'x10': 0x03,
        },
        'level': {
            'insteon': 0x11,
            'x10': 0x10,
        },
    }

    def _init_(self, **kwargs):
        self.load_deferred = None  # Prevents loader from moving on past _start_ until we are done.
        self.load_deferred_dl = None  # Prevents loader from moving on past _start_ until we are done.
        self.startable = False # track when load has completed...
        self.call_later_set_and_hold = None
        self.plm_history = deque([], 50)
        self.status = True  # InsteonAPI checks this..
        self.insteonapi = None  # pointer to the insteon api module.
        self.ready = False

    def _start_(self, **kwargs):
        if self.insteonapi is None:
            logger.error("Insteon PLM module doesn't have required Insteon API module. Disabling PLM.")
            return

        d1 = self.connect_plm()
        self.load_deferred = Deferred()
        self.load_deferred_dl = DeferredList(d1, self.load_deferred)
        return self.load_deferred_dl

    @inlineCallbacks
    def connect_plm(self):
        try:
            serial_port = self._module_variables_cached['port']['values'][0]
        except:
            serial_port = '/dev/insteon'

        self.plm_connection = yield ensureDeferred(
            plm.Connection.create(device=serial_port, loop=self._event_loop))
        self.plm_protocol = self.plm_connection.protocol
        self.plm_devices = self.plm_connection.protocol.devices._devices
        self.plm_protocol.add_poll_completed_callback(self.plm_poll_completed)
        self.plm_protocol.add_update_callback(self.plm_update_device, {})
        self.plm_protocol.add_message_callback(self.plm_set_and_hold, {'code': 0x54, 'event': 0x03})
        self.ready = True

    def plm_poll_completed(self):
        if self.load_deferred_dl is not None and self.load_deferred_dl.called is False:
            self.load_deferred_dl.callback(10)

    def _stop_(self, **kwargs):
        if self.load_deferred is not None and self.load_deferred.called is False:
            self.load_deferred.callback(1)  # if we don't check for this, we can't stop!
        if self.load_deferred_dl is not None and self.load_deferred_dl.called is False:
            self.load_deferred_dl.callback(1)  # if we don't check for this, we can't stop!

    def insteonapi_init(self, insteonapi):  # the api module giving us a reference to itself.
        self.insteonapi = insteonapi

    def insteonplm_insteonapi_interfaces(self, **kwargs):
        """
        This is a hook implemented by the Insteon api module. This simply tells the Insteon API module that we can support
        Insteon device interactions.

        :param kwargs: 
        :return: 
        """
        try:
            priority = self._module_variables_cached['port']['values'][0]
        except:
            priority = 0

        # logger.warn("Registering Insteon PLM with Insteon API as priority 0.")
        return {'priority': priority, 'module': self}

    def device_command(self, **kwargs):
        """
        Called by the insteonapi module to send a command.
        :param kwargs: 
        :return: 
        """
        logger.debug("in device_command. Ready: {ready}", ready=self.ready)
        if self.ready is False:
            return ('failed', 'PLM interface not ready.')
        device = kwargs['device']
        command = kwargs['command']
        inputs = kwargs['inputs']
        request_id = kwargs['request_id']

        device_variables = device.device_variables_cached
        address = Address(device_variables['address']['values'][0])
        # print("plm plm_devices: %s" % self.plm_devices)
        # print("plm device_variables: %s" % device_variables)
        plm_device = self.plm_devices[address.hex]

        do_command = command.machine_label

        fast = do_command.endswith('fast')

        if 'brightness' in inputs:
            brightness = float(inputs['brightness'])
        elif 'percent' in inputs:
            brightness = translate_int_value(float(inputs['percent']), 0, 100, 0, 255)
        else:
            brightness = 255

        if 'ramprate' in inputs:
            ramprate = int(inputs['ramprate'])
        else:
            ramprate = None

        if do_command.startswith('on'):
            # else:
            #     brightness = 255
            self.plm_protocol.turn_on(address, brightness=brightness, ramprate=ramprate, fast=fast)
        elif do_command == 'set_brightness':
            self.plm_protocol.turn_on(address, brightness=brightness)
        elif do_command == 'brighten':
            brightness = self.insteonapi.devices[address.human]['onlevel'] + 26  # about 11-12 steps
            self.plm_protocol.turn_on(address, brightness=brightness)
        elif do_command == 'dim':
            brightness = self.insteonapi.devices[address.human]['onlevel'] - 26  # about 11-12 steps
            self.plm_protocol.turn_on(address, brightness=brightness)
        elif do_command == 'dim_start':
            self.plm_protocol.send_insteon_standard(plm_device, '23', '00')
        elif do_command == 'dim_stop':
            self.plm_protocol.send_insteon_standard(plm_device, '24', '00')
        elif do_command == 'dim_start':
            self.plm_protocol.send_insteon_standard(plm_device, '23', '01')
        elif do_command == 'dim_stop':
            self.plm_protocol.send_insteon_standard(plm_device, '24', '01')
        elif do_command.startswith('off'):
            fast = do_command.endswith('fast')
            self.plm_protocol.turn_off(address, ramprate=ramprate, fast=fast)
        else:
            return ('failed', 'Unknown command: %s' % do_command)

        return ('done', 'Command delivered to PLM interface.')

    def get_plm_device(self, address):
        address = Address(address)
        # print("address: %s -> %s"  % (addr, address.__dict__))
        device = self.devices[address.hex]

    def get_found_devices(self):
        """
        Called by Insteon API to get all devices linked to the PLM device.
        
        :return: 
        """
        results = {}
        for address, device in self.plm_devices.items():
            results[device['address']] = device
        return results

    def plm_set_and_hold(self, message):
        """
        The PLM device had it's set button pressed for a while. Lets update the device list after a bit.
        :param message: 
        :return: 
        """
        # print("got a plm set and hold: %s" % message)
        if self.call_later_set_and_hold is not None:
            try:
                self.call_later_set_and_hold.cancel()
            except:
                pass
        self.call_later_set_and_hold = reactor.callLater(3, self.plm_protocol.load_all_link_database)
        # print("Devices: %s" % self.plm_devices )

    def plm_message(self, message):
        self.plm_history.append(message)

    def plm_update_device(self, message):
        # print("UYpdate from address: %s"  % message.cmd1)
        # print("UYpdate from address: %s"  % message.__dict__)
        device = self.plm_devices[message.address.hex]
        # print("Update from device: %s" % device)

        # for now, just handle lights...
        if 'onlevel' not in device:
            return

        onlevel = device['onlevel']
        if onlevel == 0:
            command_label = 'off'
        else:
            command_label = 'on'

        self.insteonapi.insteon_device_update(device, command_label)
