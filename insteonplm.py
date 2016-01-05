#This file was created by Yombo for use with Yombo Python Gateway automation
#software.  Details can be found at https://yombo.net
"""
Insteon PLM
===========

This file is an adaptation of the pytomation 
(https://github.com/zonyl/pytomation) from the interfaces/insteon.py file.  It
has been adapted to work with Yombo Gateway. Specifically, this file is from
git hash: b7e3dd762a6b3d14b5ffc5e6b37f4b62a9b3f676

Original authors:

* Pyjamasam@github <>
* Jason Sharpee <jason@sharpee.com>  http://www.sharpee.com
* George Farris <farrisg@gmsys.com>

* Based loosely on the Insteon_PLM.pm code:

  * Expanded by Gregg Liming <gregg@limings.net>

This module interfaces between the Insteon API module and an Insteon
PLM module plugged into the local gateway. During installation, the
user will be prompted to enter information to locate the Insteon
PLM device on the local gateway.

Parts of this file are from the x10heyu module as well as PyInsteon.
As such, this file is not distributed as part of the Yombo gateway software,
due to licensing requirements, but as a seperate download to be optionally
installed seperately at the users request.

Insteon Interface for the following PLMs:

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
:copyright: Copyright 2012-2013 by Yombo.
:license: GPL(v1)
:organization: `Yombo <http://www.yombo.net>`_
"""
from collections import deque
import binascii
import hashlib
import struct
from serial.serialutil import SerialException
import time
import binascii
import struct
import hashlib
from collections import deque
import traceback

from twisted.internet import utils, reactor
from twisted.internet.task import LoopingCall
from twisted.internet.protocol import Protocol
from twisted.internet.serialport import SerialPort

from yombo.core.module import YomboModule
from yombo.core.helpers import getComponent, sleep
from yombo.core.log import getLogger
from yombo.core.lookupdict import LookupDict

logger = getLogger("modules.insteonplm")

def _byteIdToStringId(idHigh, idMid, idLow):
    return '%02X.%02X.%02X' % (idHigh, idMid, idLow)


def _cleanStringId(stringId):
    return stringId[0:2] + stringId[3:5] + stringId[6:8]


def _stringIdToByteIds(stringId):
    return binascii.unhexlify(_cleanStringId(stringId))


def _buildFlags(stdOrExt=None):
    #todo: impliment this
    if stdOrExt:
        return '\x1f'  # Extended command
    else:
        return '\x0f'  # Standard command


def hashPacket(packetData):
    return hashlib.md5(packetData).hexdigest()


def simpleMap(value, in_min, in_max, out_min, out_max):
    #stolen from the arduino implimentation.  I am sure there is a nice python way to do it, but I have yet to stublem across it
    return (float(value) - float(in_min)) * (float(out_max) - float(out_min)) / (float(in_max) - float(in_min)) + float(out_min);


'''
KEYPADLINC Information

D1   Button or Group number
D2   Controls sending data to device 
D3   Button's LED follow mask  - 0x00 - 0xFF
D4   Button's LED-off mask  - 0x00 - 0xFF
D5   X10 House code, we don't support
D6   X10 Unit code, we don't support
D7   Button's Ramp rate - 0x00 - 0x1F
D8   Button's ON Level  - 0x00 - 0xFF
D9   Global LED Brightness - 0x11 - 0x7F
D10  Non-toggle Bitmap If bit = 0, associated button is Toggle, If bit = 1, button is Non-toggle - 0x00 - 0xFF
D11  Button-LED State Bitmap If bit = 0, associated button's LED is Off, If bit = 1 button's LED is On - 0x00-0xFF
D12  X10 all bitmap
D13  Button Non-Toggle On/Off bitmap, 0 if non-toggle sends Off, 1 if non-toggle sends On
D14  Button Trigger-ALL-Link Bitmap If bit = 0, associated button sends normal Command If bit = 0, button sends ED 0x30 Trigger ALL-Link Command to first device in ALDB

D2 = 01  Is response to a get data request
     02  Set LED follow mask, D3 0x00-0xFF, D4-D14 unused set to 0x00
     03  Set LED off mask, D3 0x00-0xFF, D4-D14 unused set to 0x00
     04  Set X10 address for button - unsupported
     05  Set Ramp rate for button, D3 0x00-0x1F, D4-D14 unused set to 0x00
     06  Set ON Level for button, D3 0x00-0x1F, D4-D14 unused set to 0x00
     07  Set Global LED brightness, D3 0x11-0x7F, D4-D14 unused set to 0x00
     08  Set Non-Toggle state for button, D3 0x00-0x01, D4-D14 unused set to 0x00
     09  Set LED state for button, D3 0x00-0x01, D4-D14 unused set to 0x00
     0A  Set X10 all on - unsupported
     0B  Set Non-Toggle ON/OFF state for button, D3 0x00-0x01, D4-D14 unused set to 0x00
     0C  Set Trigger-ALL-Link State for button, D3 0x00-0x01, D4-D14 unused set to 0x00
     0D-FF Unused

00 01 20 00 00 20 00 00 3F 00 03 00 00 00  Main button ON
 1     3     5     7     9    11    13     A1 button ON

00 01 20 00 00 20 00 00 3F 00 C0 00 00 00  Main button OFF
00 01 20 00 00 20 00 00 3F 00 C4 00 00 00  A ON
00 01 20 00 00 20 00 00 3F 00 C8 00 00 00  B ON
00 01 20 00 00 20 00 00 3F 00 CC 00 00 00  A and B ON
00 01 20 00 00 20 00 00 3F 00 D0 00 00 00  C ON
00 01 20 00 00 20 00 00 3F 00 D4 00 00 00  A and C ON
00 01 20 00 00 20 00 00 3F 00 DC 00 00 00  A, B and C ON
'''


class InsteonPLM(YomboModule):
    """
    The primary class...
    """
    #pytomation items
    #(address:engineVersion) engineVersion 0x00=i1, 0x01=i2, 0x02=i2cs
    deviceList = {}         # Dynamically built list of devices [address,devcat,subcat,firmware,engine,name]
    currentCommand = ""
    cmdQueueList = []   	# List of orphaned commands that need to be dealt with
    spinTime = 0.1   		# _readInterface loop time
    extendedCommand = False	# if extended command ack expected from PLM
    statusRequest = False   # Set to True when we do a status request
    lastUnit = ""		# last seen X10 unit code

    def _init_(self):
        logger.info("&&&&: Insteon Module Devices: %s" % self._Devices)
        logger.info("&&&&: Insteon Module DeviceTypes: %s" % self._DeviceTypes)
        self._ModDescription = "Insteon command interface"
        self._ModAuthor = "Mitch Schwenk @ Yombo"
        self._ModUrl = "http://www.yombo.net"

        self.startable = False # track when load has completed...
        self.pending = False
        self.queue = deque()
        self.checkQueueLoop = LoopingCall(self.checkQueue)

        self._outboundQueue = deque()
        self._outboundCommandDetails = dict()
        self._retryCount = dict()
        self._readBuffer = ''
        self._serialProtocol = None

        #pytomation items
        # Response sizes do not include the start of message (0x02) and the command
        self._modemCommands = {'60': {  # Get IM Info
                                    'responseSize' : 7,
                                    'callBack' : self._process_PLMInfo
                                  },
                                '61': { # Send All Link Command
                                    'responseSize' : 4,
                                    'callBack' : self._process_StandardInsteonMessagePLMEcho
                                  },
                                '62': { # Send Standard or Extended Message
                                    'responseSize' : 7,
                                    'callBack' : self._process_StandardInsteonMessagePLMEcho
                                  },
                                '63': { # Send X10
                                    'responseSize' : 3,
                                    'callBack' : self._process_StandardX10MessagePLMEcho
                                  },
                                '64': { # Start All Linking
                                    'responseSize' : 3,
                                    'callBack' : self._process_StandardInsteonMessagePLMEcho
                                  },
                                '65': { # Cancel All Linking
                                    'responseSize' : 1,
                                    'callBack' : self._process_StandardInsteonMessagePLMEcho
                                  },
                                '69': { # Get First All Link Record
                                    'responseSize' : 1,
                                    'callBack' : self._process_StandardInsteonMessagePLMEcho
                                  },
                                '6A': { # Get Next All Link Record
                                    'responseSize' : 1,
                                    'callBack' : self._process_StandardInsteonMessagePLMEcho
                                  },
                                '50': { # Received Standard Message
                                    'responseSize' : 9,
                                    'callBack' : self._process_InboundStandardInsteonMessage
                                  },
                                '51': { # Received Extended Message
                                    'responseSize' : 23,
                                    'callBack' : self._process_InboundExtendedInsteonMessage
                                  },
                                '52': { # Received X10
                                    'responseSize' : 2, # originally 3
                                    'callBack' : self._process_InboundX10Message
                                 },
                                '56': { # All Link Record Response
                                    'responseSize' : 4,
                                    'callBack' : self._process_InboundAllLinkCleanupFailureReport
                                  },
                                '57': { # All Link Record Response
                                    'responseSize' : 8,
                                    'callBack' : self._process_InboundAllLinkRecordResponse
                                  },
                                '58': { # All Link Record Response
                                    'responseSize':1,
                                    'callBack':self._process_InboundAllLinkCleanupStatusReport
                                  },
                            }
        self._modemExtCommands = {'62': { # Send Standard or Extended Message
                                    'responseSize': 21,
                                    'callBack':self._process_ExtendedInsteonMessagePLMEcho
                                  },
                            }

        self._insteonCommands = {
                                    #Direct Messages/Responses
                                    'SD03': {        #Product Data Request (generally an Ack)
                                        'callBack' : self._handle_StandardDirect_IgnoreAck,
                                        'validResponseCommands' : ['SD03']
                                    },
                                    'SD0D': {        #Get InsteonPLM Engine
                                        'callBack' : self._handle_StandardDirect_EngineResponse,
                                        'validResponseCommands' : ['SD0D']
                                    },
                                    'SD0F': {        #Ping Device
                                        'callBack' : self._handle_StandardDirect_AckCompletesCommand,
                                        'validResponseCommands' : ['SD0F']
                                    },
                                    'SD10': {        #ID Request    (generally an Ack)
                                        'callBack' : self._handle_StandardDirect_IgnoreAck,
                                        'validResponseCommands' : ['SD10', 'SB01']
                                    },
                                    'SD11': {        #Devce On
                                        'callBack' : self._handle_StandardDirect_AckCompletesCommand,
                                        'validResponseCommands' : ['SD11', 'SDFF', 'SD00']
                                    },
                                    'SD12': {        #Devce On Fast
                                        'callBack' : self._handle_StandardDirect_AckCompletesCommand,
                                        'validResponseCommands' : ['SD12']
                                    },
                                    'SD13': {        #Devce Off
                                        'callBack' : self._handle_StandardDirect_AckCompletesCommand,
                                        'validResponseCommands' : ['SD13']
                                    },
                                    'SD14': {        #Devce Off Fast
                                        'callBack' : self._handle_StandardDirect_AckCompletesCommand,
                                        'validResponseCommands' : ['SD14']
                                    },
                                    'SD15': {        #Brighten one step
                                        'callBack' : self._handle_StandardDirect_AckCompletesCommand,
                                        'validResponseCommands' : ['SD15']
                                    },
                                    'SD16': {        #Dim one step
                                        'callBack' : self._handle_StandardDirect_AckCompletesCommand,
                                        'validResponseCommands' : ['SD16']
                                    },
                                    'SD19': {        #Light Status Response
                                        'callBack' : self._handle_StandardDirect_LightStatusResponse,
                                        'validResponseCommands' : ['SD19']
                                    },
                                    'SD2E': {        #Light Status Response
                                        'callBack' : self._handle_StandardDirect_AckCompletesCommand,
                                        'validResponseCommands' : ['SD2E']
                                    },

				    #X10 Commands
                                    'XD03': {        #Light Status Response
                                        'callBack' : self._handle_StandardDirect_AckCompletesCommand,
                                        'validResponseCommands' : ['XD03']
                                    },
                                    
                                    #Broadcast Messages/Responses
                                    'SB01': {
                                                    #Set button pushed
                                        'callBack' : self._handle_StandardBroadcast_SetButtonPressed
                                    },
                                    'SBXX12': {
                                                    #Fast On Command
                                        'callBack' : self._handle_StandardBroadcast_SetButtonPressed,
                                        'validResponseCommands' : ['SB12']
                                    },
                                    'SBXX14': {
                                                    #Fast Off Command
                                        'callBack' : self._handle_StandardBroadcast_SetButtonPressed,
                                        'validResponseCommands' : ['SB14']
                                    },

                                    #Unknown - Seems to be light level report
                                    'SDFF': {
                                             },
                                    'SD00': {
                                             },
                                }

        self._x10HouseCodes = Lookup(zip((
                            'm',
                            'e',
                            'c',
                            'k',
                            'o',
                            'g',
                            'a',
                            'i',
                            'n',
                            'f',
                            'd',
                            'l',
                            'p',
                            'h',
                            'n',
                            'j' ),xrange(0x0, 0xF)))

        self._x10UnitCodes = Lookup(zip((
                             '13',
                             '5',
                             '3',
                             '11',
                             '15',
                             '7',
                             '1',
                             '9',
                             '14',
                             '6',
                             '4',
                             '12',
                             '16',
                             '8',
                             '2',
                             '10'
                             ),xrange(0x0,0xF)))

        self._x10Commands = Lookup(zip((
                             'allUnitsOff',
                             'allLightsOn',
                             'on',
                             'off',
                             'dim',
                             'bright',
                             'allLightsOff',
                             'ext1',
                             'hail',
                             'hailAck',
                             'ext3',
                             'unused1',
                             'ext2',
                             'statusOn',
                             'statusOff',
                             'statusReq'
                             ),xrange(0x0,0xF)))

        self._command = LookupDict(
            {
                       'on'         :{'primary' : {
                                                    'insteon':0x11,
                                                    'x10':0x02,
                                                    'upb':0x00
                                                  },
                                     'secondary' : {
                                                    'insteon':0xff,
                                                    'x10':None,
                                                    'upb':None
                                                    },
                                     },
                       'faston'    :{'primary' : {
                                                    'insteon':0x12,
                                                    'x10':0x02,
                                                    'upb':0x00
                                                  },
                                     'secondary' : {
                                                    'insteon':0xff,
                                                    'x10':None,
                                                    'upb':None
                                                    },
                                     },
                       'off'         :{'primary' : {
                                                    'insteon':0x13,
                                                    'x10':0x03,
                                                    'upb':0x00
                                                  },
                                     'secondary' : {
                                                    'insteon':0x00,
                                                    'x10':None,
                                                    'upb':None
                                                    },
                                     },

                       'fastoff'    :{'primary' : {
                                                    'insteon':0x14,
                                                    'x10':0x03,
                                                    'upb':0x00
                                                  },
                                     'secondary' : {
                                                    'insteon':0x00,
                                                    'x10':None,
                                                    'upb':None
                                                    },
                                     },
                       'level'    :{'primary' : {
                                                    'insteon':0x11,
                                                    'x10':0x0a,
                                                    'upb':0x00
                                                  },
                                     'secondary' : {
                                                    'insteon':0x88,
                                                    'x10':None,
                                                    'upb':None
                                                    },
                                     },
            })

#        self._allLinkDatabase = dict()
        self._intersend_delay = 0.85 #850ms between network sends

        # This maps Yombo Commands to Insteon Commands. TODO: Add more Yombo Commands to match. 
        self.functionToInsteon = {
          'ON'            : 'SD11',
          'OFF'           : 'SD13',
          'DIM'           : 'SD15',
          'BRIGHTEN'      : 'SD16',
          'MICRO_DIM'     : 'SD15',
          'MICRO_BRIGHTEN': 'SD16' }
        
        self.__pendingCommandDetails = dict() 
        self.__running = False
        self.__loaded = False
        self.__lastPacketHash = None

        self._buffer = ''

        self._attempts = 0
        self._interval = 3
        self._baudrate = '19200'
        self._connected = False
        self._hasStarted = False # true if self.start has been called
        self.insteonCmds = {}

    def _load_(self):
        self.APIModule = getComponent("yombo.gateway.modules.InsteonAPI")
        logger.debug("######== {modvars}", modvars=self._ModVariables);

        self.PLMType = "serial"  #serial, network, etc etc later...
        self.PLMAddress = self._ModuleVariables['portPath']['value'][0]

#todo: convert to exception
        if self.PLMAddress is None:
            logger.error("InsteonPLM cannot load, PLM address empty.")
            return
        return self._startConnection()
        
    def _startConnection(self):
        """serial
        Make the actual connection to the PLM device..
        """
        if self.PLMType == "serial":
          try:
            self.SerialInterface = SerialPort(InsteonPLMSerialProtocol(self), self.PLMAddress, reactor, baudrate=self._baudrate)
            self._connected = True
          except SerialException, error:
            self._attempts += 1
            if self._attempts % 10 ==1:
                logger.warn("Unable to connect to InsteonPLM serial port. Will continue trying. Attempt: {attempts}, Reason: {error}", reason=self._attempts, error=error)
            reactor.callLater(self._interval, self._startConnection)
          self.__running = True
          self.__loaded = True
        else:
            logger.warn("That connection method dosn't exist yet.")

    def connected(self):
        """
        Called by the interface protocol once connected..
        """
        pass

    def _start_(self):
        self._hasStarted = True
        if self._connected is True:
            self.checkQueueLoop.start(2)

    def _stop_(self):
        pass

    def _unload_(self):
        self.__loaded = False
        
        self.__running = False
        return

    def sendInsteonCmd(self, insteonCmd):
        """
        Commands from Insteon API come into here. They need to be processed
        and sent to interface.
        """
#        logger.debug("x10cmds: %s", self.APIModule.x10cmds)
        
        self.insteonCmds[insteonCmd.originalMessage.msgUUID] = insteonCmd
        logger.warn("insteonCommnd: {icmd}", icmd=insteonCmd.dump())

        self.command(insteonCmd)
        
    def checkQueue(self):
        if self.pending is False:
            if len(self.queue) > 0:
                self.pending = True
                newitem = self.queue.pop()
                self._send(newitem)
            
    #pytomation items
    def _waitForCommandToFinish(self, commandExecutionDetails, timeout=None):

        if type(commandExecutionDetails) != type(dict()):
            logger.error("Unable to wait without a valid commandExecutionDetails parameter")
            return False

        waitEvent = commandExecutionDetails['waitEvent']
        commandHash = commandExecutionDetails['commandHash']

        realTimeout = 2  # default timeout of 2 seconds
        if timeout:
            realTimeout = timeout

        timeoutOccured = False

        sleep(realTimeout)

        if not timeoutOccured:
            if commandHash in self._commandReturnData:
                return self._commandReturnData[commandHash]
            else:
                return True
        else:
            #re-queue the command to try again
            self._commandLock.acquire()

            if self._retryCount[commandHash] >= 5:
                #too many retries.  Bail out
                self._commandLock.release()
                return False

            self._logger.debug("Timed out for %s - Requeueing (already had %d retries)" % \
                (commandHash, self._retryCount[commandHash]))

            requiresRetry = True
            if commandHash in self._pendingCommandDetails:
                self._outboundCommandDetails[commandHash] = \
                    self._pendingCommandDetails[commandHash]

                del self._pendingCommandDetails[commandHash]

                self._outboundQueue.append(commandHash)
                self._retryCount[commandHash] += 1
            else:
                self._logger.debug("Interesting.  timed out for %s, but there are no pending command details" % commandHash)
                #to prevent a huge loop here we bail out
                requiresRetry = False

            try:
                self._logger.debug("Removing Lock " + str( self._commandLock))
                self._commandLock.release()
            except:
                self._logger.error("Could not release Lock! " + str(self._commandLock))

            if requiresRetry:
                return self._waitForCommandToFinish(commandExecutionDetails,
                                                    timeout=timeout)
            else:
                return False


    def _sendInterfaceCommand(self, modemCommand, commandDataString = None, extraCommandDetails = None):
        self.currentCommand = [modemCommand, commandDataString, extraCommandDetails]
        modemCommand = binascii.unhexlify(modemCommand)
        bytesToSend = ''
        returnValue = False
        try:
#            bytesToSend = self.MODEM_PREFIX + binascii.unhexlify(modemCommand)
            bytesToSend = '\x02' + modemCommand
            if commandDataString != None:
                bytesToSend += commandDataString
            commandHash = hashPacket(bytesToSend)

            if commandHash in self._outboundCommandDetails:
                #duplicate command.  Ignore
                pass

            else:
                basicCommandDetails = {'bytesToSend': bytesToSend,
                                       'modemCommand': modemCommand}

                if extraCommandDetails != None:
                    basicCommandDetails = dict(
                                       basicCommandDetails.items() + \
                                       extraCommandDetails.items())

                self._outboundCommandDetails[commandHash] = basicCommandDetails

                self._outboundQueue.append(commandHash)
                self._retryCount[commandHash] = 0

                logger.info("Queued: {commandHash}", commandHash=commandHash)

                returnValue = {'commandHash': commandHash}

        except Exception, ex:
            print traceback.format_exc()

        return returnValue

    def _readInterface(self, lastPacketHash):
        #check to see if there is anyting we need to read
        firstByte = self._serialProtocol.readData(1)
        logger.warn("firstByte: {firstByte}", firstByte=firstByte)
#        return

        try:
            if len(firstByte) == 1:
                #got at least one byte.  Check to see what kind of byte it is (helps us sort out how many bytes we need to read now)
                
                if firstByte[0] == '\x02':
                    #modem command (could be an echo or a response)
                    #read another byte to sort that out
                    secondByte = self._serialProtocol.readData(1)
                    logger.warn("secondByte: {secondByte}", secondByte=secondByte)

                    responseSize = -1
                    callBack = None
                    
                    if self.extendedCommand:
                        # set the callback and response size expected for extended commands
                        modemCommand = binascii.hexlify(secondByte).upper()
                        if self._modemExtCommands.has_key(modemCommand):
                            if self._modemExtCommands[modemCommand].has_key('responseSize'):
                                responseSize = self._modemExtCommands[modemCommand]['responseSize']
                            if self._modemExtCommands[modemCommand].has_key('callBack'):
                                callBack = self._modemExtCommands[modemCommand]['callBack']

                    else:
                        # set the callback and response size expected for standard commands
                        modemCommand = binascii.hexlify(secondByte).upper()
                        logger.warn("bbb: modemCommand= {modemCommand}", modemCommand=modemCommand)

                        if self._modemCommands.has_key(modemCommand):
                            if self._modemCommands[modemCommand].has_key('responseSize'):
                                responseSize = self._modemCommands[modemCommand]['responseSize']
                            if self._modemCommands[modemCommand].has_key('callBack'):
                                callBack = self._modemCommands[modemCommand]['callBack']
    
                    if responseSize != -1:
                        remainingBytes = self._serialProtocol.readData(responseSize)
                        logger.warn("{responseSize} remainingBytes: {remainingBytes}", responseSize=responseSize, remainingBytes=remainingBytes)
                        currentPacketHash = hashPacket(firstByte + secondByte + remainingBytes)
                        logger.debug("Receive< " + self.hex_dump(firstByte + secondByte + remainingBytes, len(firstByte + secondByte + remainingBytes)) + currentPacketHash + "\n")
    
                        if lastPacketHash and lastPacketHash == currentPacketHash:
                            logger.warn("bbb")
                            #duplicate packet.  Ignore
                            pass
                        else:
                            logger.warn("ccc")
                            if callBack:
                                logger.warn("ddd")
                                callBack(firstByte + secondByte + remainingBytes)
                            else:
                                logger.warn("eee")
                                logger.debug("No callBack defined for for modem command {modemCommand}", modemCommand=modemCommand)
    
                        self._lastPacketHash = currentPacketHash
                        self.spinTime = 0.2     #reset spin time, there were no naks, Don't set this lower
                    else:
                        logger.debug("No responseSize defined for modem command {modemCommand}", modemCommand=modemCommand)
                        
                elif firstByte[0] == '\x15':
                    self.spinTime += 0.2
                    logger.debug("Received a Modem NAK! Resending command, loop time {spinTime}", spinTime=self.spinTime)
                    if self.spinTime < 12.0:
                        self._sendInterfaceCommand(self.currentCommand[0], self.currentCommand[1], self.currentCommand[2])
                    else:
                        logger.debug("Too many NAK's! Device not responding...")
                else:
                    logger.debug("Unknown first byte {firstByte}", firstByte=binascii.hexlify(firstByte[0]))
                
                self.extendedCommand = False	# go back to standard commands as default
                
            else:
                self._checkCommandQueue()
                #print "Sleeping"
                #X10 is slow.  Need to adjust based on protocol sent.  Or pay attention to NAK and auto adjust
                sleep(self.spinTime)
        except TypeError, ex:
            pass

    def _sendStandardP2PInsteonCommand(self, destinationDevice, commandId1, commandId2):
        logger.debug("Command: {destinationDevice} {comandID1} {commandID2}", destinationDevice=destinationDevice, comandID1=commandId1, commandID2=commandId2)
        return self._sendInterfaceCommand('62', _stringIdToByteIds(destinationDevice) + _buildFlags() + binascii.unhexlify(commandId1) + binascii.unhexlify(commandId2), extraCommandDetails = { 'destinationDevice': destinationDevice, 'commandId1': 'SD' + commandId1, 'commandId2': commandId2})

    def _sendStandardAllLinkInsteonCommand(self, destinationGroup, commandId1, commandId2):
        logger.debug("Command: {destinationGroup} {comandID1} {commandID2}", destinationGroup=destinationGroup, comandID1=commandId1, commandID2=commandId2)
        return self._sendInterfaceCommand('61', binascii.unhexlify(destinationGroup) + binascii.unhexlify(commandId1) + binascii.unhexlify(commandId2),
                extraCommandDetails = { 'destinationDevice': destinationGroup, 'commandId1': 'SD' + commandId1, 'commandId2': commandId2})

    def _getX10UnitCommand(self,deviceId):
        "Send just an X10 unit code message"
        deviceId = deviceId.lower()
        return "%02x00" % ((self._x10HouseCodes[deviceId[0:1]] << 4) | self._x10UnitCodes[deviceId[1:2]])

    def _getX10CommandCommand(self,deviceId,commandCode):
        "Send just an X10 command code message"
        deviceId = deviceId.lower()
        return "%02x80" % ((self._x10HouseCodes[deviceId[0:1]] << 4) | int(commandCode,16))

    def _sendStandardP2PX10Command(self,destinationDevice,commandId1, commandId2 = None):
        # X10 sends 1 complete message in two commands
        logger.debug("Command: {destinationDevice} {comandID1} {commandID2}", destinationDevice=destinationDevice, comandID1=commandId1, commandID2=commandId2)
        logger.debug("C: {getX10Command}", getX10Command=self._getX10UnitCommand(destinationDevice))
        logger.debug("c1: {getX10CommandCommand}", getX10CommandCommand=self._getX10CommandCommand(destinationDevice, commandId1))
            
        self._sendInterfaceCommand('63', binascii.unhexlify(self._getX10UnitCommand(destinationDevice)))

        return self._sendInterfaceCommand('63', binascii.unhexlify(self._getX10CommandCommand(destinationDevice, commandId1)))

    #low level processing methods
    def _process_PLMInfo(self, responseBytes):
        (modemCommand, InsteonCommand, idHigh, idMid, idLow, deviceCat, deviceSubCat, firmwareVer, acknak) = struct.unpack('BBBBBBBBB', responseBytes)
        
        foundCommandHash = None
        #find our pending command in the list so we can say that we're done (if we are running in syncronous mode - if not well then the caller didn't care)
        for (commandHash, commandDetails) in self._pendingCommandDetails.items():
#            if binascii.unhexlify(commandDetails['modemCommand']) == chr(modemCommand):
            if commandDetails['modemCommand'] == '\x60':
                #Looks like this is our command.  Lets deal with it
                #self._commandReturnData[commandHash] = { 'id': _byteIdToStringId(idHigh,idMid,idLow), 'deviceCategory': '%02X' % deviceCat, 'deviceSubCategory': '%02X' % deviceSubCat, 'firmwareVersion': '%02X' % firmwareVer }    
                self.plmAddress = _byteIdToStringId(idHigh,idMid,idLow).upper()
                
                waitEvent = commandDetails['waitEvent']
                waitEvent.set()

                foundCommandHash = commandHash
                break

        if foundCommandHash:
            del self._pendingCommandDetails[foundCommandHash]
        else:
            logger.warn("Unable to find pending command details for the following packet: {hexdump}", hexdump=self.hex_dump(responseBytes, len(responseBytes)))

    def _process_StandardInsteonMessagePLMEcho(self, responseBytes):
        #print utilities.hex_dump(responseBytes, len(responseBytes))
        #echoed standard message is always 9 bytes with the 6th byte being the command
        #here we handle a status request as a special case the very next received message from the 
        #PLM will most likely be the status response.
        if ord(responseBytes[1]) == 0x62:
            if len(responseBytes) == 9:  # check for proper length
                if ord(responseBytes[6]) == 0x19 and ord(responseBytes[8]) == 0x06:  # get a light level status
                    self.statusRequest = True

    def _process_StandardX10MessagePLMEcho(self, responseBytes):
        # Just ack / error echo from sending an X10 command
        pass

    def _validResponseMessagesForCommandId(self, commandId):
        logger.debug('ValidResponseCheck: {commandID}', commandID=self.hex_dump(commandId))
        if self._insteonCommands.has_key(commandId):
            commandInfo = self._insteonCommands[commandId]
            logger.debug('ValidResponseCheck2: {commandInfo}', commandInfo=str(commandInfo))
            if commandInfo.has_key('validResponseCommands'):
                logger.debug('ValidResponseCheck3: {validResponseCommands}', validResponseCommands=str(commandInfo['validResponseCommands']))
                return commandInfo['validResponseCommands']

        return False

    def _process_InboundStandardInsteonMessage(self, responseBytes):
        if len(responseBytes) != 11:
            logger.error("responseBytes< {hexDump}", hexDump=self.hex_dump(responseBytes, len(responseBytes)) + "\n")
            logger.error("Command incorrect length. Expected 11, Received {responseBytes}", responseBytes=len(responseBytes))
            return

        (modemCommand, insteonCommand, fromIdHigh, fromIdMid, fromIdLow, toIdHigh, toIdMid, toIdLow, messageFlags, command1, command2) = struct.unpack('BBBBBBBBBBB', responseBytes)

        foundCommandHash = None
        waitEvent = None

        #check to see what kind of message this was (based on message flags)
        isBroadcast = messageFlags & (1 << 7) == (1 << 7)
        isDirect = not isBroadcast
        isAck = messageFlags & (1 << 5) == (1 << 5)
        isNak = isAck and isBroadcast

        insteonCommandCode = "%02X" % command1
        if isBroadcast:
            #standard broadcast
            insteonCommandCode = 'SB' + insteonCommandCode
        else:
            #standard direct
            insteonCommandCode = 'SD' + insteonCommandCode

        if self.statusRequest:
            insteonCommandCode = 'SD19'
            
            #this is a strange special case...
            #lightStatusRequest returns a standard message and overwrites the cmd1 and cmd2 bytes with "data"
            #cmd1 (that we use here to sort out what kind of incoming message we got) contains an 
            #"ALL-Link Database Delta number that increments every time there is a change in the addressee's ALL-Link Database"
            #which makes is super hard to deal with this response (cause cmd1 can likley change)
            #for now my testing has show that its 0 (at least with my dimmer switch - my guess is cause I haven't linked it with anything)
            #so we treat the SD00 message special and pretend its really a SD19 message (and that works fine for now cause we only really
            #care about cmd2 - as it has our light status in it)
#            insteonCommandCode = 'SD19'

        #print insteonCommandCode

        #find our pending command in the list so we can say that we're done (if we are running in syncronous mode - if not well then the caller didn't care)
        for (commandHash, commandDetails) in self._pendingCommandDetails.items():
            #since this was a standard insteon message the modem command used to send it was a 0x62 so we check for that
#            if binascii.unhexlify(commandDetails['modemCommand']) == '\x62':
            if commandDetails['modemCommand'] == '\x62':
                originatingCommandId1 = None
                if commandDetails.has_key('commandId1'):
                    originatingCommandId1 = commandDetails['commandId1']

                validResponseMessages = self._validResponseMessagesForCommandId(originatingCommandId1)
                if validResponseMessages and len(validResponseMessages):
                    #Check to see if this received command is one that this pending command is waiting for
                    logger.debug('Valid Insteon Command Code: {insteonCommandCode}', insteonCommandCode=str(insteonCommandCode))
                    if validResponseMessages.count(insteonCommandCode) == 0:
                        #this pending command isn't waiting for a response with this command code...  Move along
                        continue
                else:
                    logger.warn("Unable to find a list of valid response messages for command {originatingCommandId1}", originatingCommandId1=originatingCommandId1)
                    continue

                #since there could be multiple insteon messages flying out over the wire, check to see if this one is 
                #from the device we sent this command to
                destDeviceId = None
                if commandDetails.has_key('destinationDevice'):
                    destDeviceId = commandDetails['destinationDevice']

                if destDeviceId:
                    if destDeviceId.upper() == _byteIdToStringId(fromIdHigh, fromIdMid, fromIdLow).upper():

                        returnData = {} #{'isBroadcast': isBroadcast, 'isDirect': isDirect, 'isAck': isAck}

                        #try and look up a handler for this command code
                        if self._insteonCommands.has_key(insteonCommandCode):
                            if self._insteonCommands[insteonCommandCode].has_key('callBack'):
                                # Run the callback
                                (requestCycleDone, extraReturnData) = self._insteonCommands[insteonCommandCode]['callBack'](responseBytes)
                                self.statusRequest = False
                                
                                if extraReturnData:
                                    returnData = dict(returnData.items() + extraReturnData.items())

                                if requestCycleDone:
                                    waitEvent = commandDetails['waitEvent']
                            else:
                                logger.warn("No callBack for insteon command code {insteonCommandCode}", insteonCommandCode=insteonCommandCode)
                                waitEvent = commandDetails['waitEvent']
                        else:
                            logger.warn("No insteonCommand lookup defined for insteon command code {insteonCommandCode}", insteonCommandCode=insteonCommandCode)

                        if len(returnData):
                            self._commandReturnData[commandHash] = returnData

                        foundCommandHash = commandHash
                        break

        if foundCommandHash is None:
            logger.warn("Unhandled packet (couldn't find any pending command to deal with it)")
            logger.warn("This could be a status message from a broadcast")
            # very few things cause this certainly a scene on or off will so that's what we assume
            
            self._handle_StandardDirect_LightStatusResponse(responseBytes)

        if waitEvent and foundCommandHash:
            waitEvent.set()
            try:
                del self._pendingCommandDetails[foundCommandHash]
                logger.debug("Command {foundCommandHash} completed", foundCommandHash=foundCommandHash)
            except:
                logger.error("Command {foundCommandHash} couldnt be deleted!", foundCommandHash=foundCommandHash)

    def _process_InboundExtendedInsteonMessage(self, responseBytes):
        (modemCommand, insteonCommand, fromIdHigh, fromIdMid, fromIdLow, toIdHigh, toIdMid, toIdLow, messageFlags, \
            command1, command2, d1,d2,d3,d4,d5,d6,d7,d8,d9,d10,d11,d12,d13,d14) = struct.unpack('BBBBBBBBBBBBBBBBBBBBBBBBB', responseBytes)        
        
        logger.info("{responseBytes}", responseBytes=self.hex_dump(responseBytes))

        foundCommandHash = None
        waitEvent = None
        
        return
        
        insteonCommandCode = "%02X" % command1
        insteonCommandCode = 'SD' + insteonCommandCode

        #find our pending command in the list so we can say that we're done (if we are running in syncronous mode - if not well then the caller didn't care)
        for (commandHash, commandDetails) in self._pendingCommandDetails.items():
            if commandDetails['modemCommand'] == '\x62':
                originatingCommandId1 = None
                if commandDetails.has_key('commandId1'):
                    originatingCommandId1 = commandDetails['commandId1']    #ex: SD03

                validResponseMessages = self._validResponseMessagesForCommandId(originatingCommandId1)
                if validResponseMessages and len(validResponseMessages):
                    #Check to see if this received command is one that this pending command is waiting for
                    if validResponseMessages.count(insteonCommandCode) == 0:
                        #this pending command isn't waiting for a response with this command code...  Move along
                        continue
                else:
                    logger.warn("Unable to find a list of valid response messages for command {originatingCommandId1}", originatingCommandId1=originatingCommandId1)
                    continue

                #since there could be multiple insteon messages flying out over the wire, check to see if this one is 
                #from the device we sent this command to
                destDeviceId = None
                if commandDetails.has_key('destinationDevice'):
                    destDeviceId = commandDetails['destinationDevice']

                if destDeviceId:
                    if destDeviceId.upper() == _byteIdToStringId(fromIdHigh, fromIdMid, fromIdLow).upper():

                        returnData = {} #{'isBroadcast': isBroadcast, 'isDirect': isDirect, 'isAck': isAck}

                        #try and look up a handler for this command code
                        if self._insteonCommands.has_key(insteonCommandCode):
                            if self._insteonCommands[insteonCommandCode].has_key('callBack'):
                                # Run the callback
                                (requestCycleDone, extraReturnData) = self._insteonCommands[insteonCommandCode]['callBack'](responseBytes)
                                
                                if extraReturnData:
                                    returnData = dict(returnData.items() + extraReturnData.items())

                                if requestCycleDone:
                                    waitEvent = commandDetails['waitEvent']
                            else:
                                logger.warn("No callBack for insteon command code {insteonCommandCode}", insteonCommandCode=insteonCommandCode)
                                waitEvent = commandDetails['waitEvent']
                        else:
                            logger.warn("No insteonCommand lookup defined for insteon command code {insteonCommandCode}", insteonCommandCode=insteonCommandCode)

                        if len(returnData):
                            self._commandReturnData[commandHash] = returnData

                        foundCommandHash = commandHash
                        break

        if foundCommandHash is None:
            logger.warn("Unhandled packet (couldn't find any pending command to deal with it)")
            logger.warn("This could be a status message from a broadcast")

        if waitEvent and foundCommandHash:
            waitEvent.set()
            del self._pendingCommandDetails[foundCommandHash]
            logger.debug("Command {foundCommandHash} completed", foundCommandHash=foundCommandHash)
    
    def _process_InboundX10Message(self, responseBytes):
        "Receive Handler for X10 Data"
        logger.warn("zzz")
        unitCode = None
        commandCode = None
        (byteB, byteC) = struct.unpack('xxBB', responseBytes)
        logger.debug("X10> {hexDump}", hexDump=self.hex_dump(responseBytes, len(responseBytes)))
        houseCode =     (byteB & 0b11110000) >> 4
        houseCodeDec = self._x10HouseCodes.get_key(houseCode)
        logger.info("X10> HouseCode {houseCodeDec}", houseCodeDec=houseCodeDec )
        unitCmd = (byteC & 0b10000000) >> 7
        if unitCmd == 0 :
            unitCode = (byteB & 0b00001111)
            unitCodeDec = self._x10UnitCodes.get_key(unitCode)
            logger.info("X10> UnitCode {unitCodeDec}", unitCodeDec=unitCodeDec )
            self.lastUnit = unitCodeDec
        else:
            commandCode = (byteB & 0b00001111)
            commandCodeDec = self._x10Commands.get_key(commandCode)
            logger.info("X10> Command: house: {houseCodeDec} unit: {lastunit} command: {command}", houseCodeDec=houseCodeDec, lastunit=self.lastUnit,  command=commandCodeDec  )
            destDeviceId = houseCodeDec.upper() + self.lastUnit
            if self._devices:
                for d in self._devices:
                    if d.address.upper() == destDeviceId:
                        # only run the command if the state is different than current
                        if (commandCode == 0x03 and d.state != State.OFF):     # Never seen one not go to zero but...
                            self._onCommand(address=destDeviceId, command=State.OFF)
                        elif (commandCode == 0x02 and d.state != State.ON):   # some times these don't go to 0xFF
                            self._onCommand(address=destDeviceId, command=State.ON)
            else: # No devices to check state, so send anyway
                if (commandCode == 0x03 ):     # Never seen one not go to zero but...
                    self._onCommand(address=destDeviceId, command=State.OFF)
                elif (commandCode == 0x02):   # some times these don't go to 0xFF
                    self._onCommand(address=destDeviceId, command=State.ON)
    
    def _process_InboundX10Message2(self, responseBytes):
        "Receive Handler for X10 Data"
        #X10 sends commands fully in two separate messages. Not sure how to handle this yet
        #TODO not implemented
        unitCode = None
        commandCode = None
        logger.debug("X10> " + self.hex_dump(responseBytes, len(responseBytes)))
             #       (insteonCommand, fromIdHigh, fromIdMid, fromIdLow, toIdHigh, toIdMid, toIdLow, messageFlags, command1, command2) = struct.unpack('xBBBBBBBBBB', responseBytes)        
#        houseCode =     (int(responseBytes[4:6],16) & 0b11110000) >> 4 
 #       houseCodeDec = X10_House_Codes.get_key(houseCode)
#        keyCode =       (int(responseBytes[4:6],16) & 0b00001111)
#        flag =          int(responseBytes[6:8],16)

    #insteon message handlers
    def _handle_StandardDirect_IgnoreAck(self, messageBytes):
        #just ignore the ack for what ever command triggered us
        #there is most likley more data coming for what ever command we are handling
        return (False, None)

    def _handle_StandardDirect_AckCompletesCommand(self, messageBytes):
        #the ack for our command completes things.  So let the system know so
        return (True, None)

    def _handle_StandardBroadcast_SetButtonPressed(self, messageBytes):
        #02 50 17 C4 4A 01 19 38 8B 01 00
        (idHigh, idMid, idLow, deviceCat, deviceSubCat, deviceRevision) = struct.unpack('xxBBBBBBxxx', messageBytes)
        return (True, {'deviceType': '%02X%02X' % (deviceCat, deviceSubCat), 'deviceRevision':'%02X' % deviceRevision})

    def _handle_StandardDirect_EngineResponse(self, messageBytes):
        #02 50 17 C4 4A 18 BA 62 2B 0D 01
        engineVersionIdentifier = messageBytes[10]
        if engineVersionIdentifier == '\x00':
            return (True, {'engineVersion': 'i1'})
        elif engineVersionIdentifier == '\x01':
            return (True, {'engineVersion': 'i2'})
        elif engineVersionIdentifier == '\x02':
            return (True, {'engineVersion': 'i2cs'})
        else:
            return (True, {'engineVersion': 'FF'})

    def _handle_StandardDirect_LightStatusResponse(self, messageBytes):
        (modemCommand, insteonCommand, fromIdHigh, fromIdMid, fromIdLow, toIdHigh, toIdMid, toIdLow, messageFlags, command1, command2) = struct.unpack('BBBBBBBBBBB', messageBytes)

        destDeviceId = _byteIdToStringId(fromIdHigh, fromIdMid, fromIdLow).upper()
        logger.debug('HandleStandDirect')
        isGrpCleanupAck = (messageFlags & 0x60) == 0x60
        isGrpBroadcast = (messageFlags & 0xC0) == 0xC0
        isGrpCleanupDirect = (messageFlags & 0x40) == 0x40
        # If we get an ack from a group command fire off a status request or we'll never know the on level (not off)
        #0x06 = Reserved ... heartbeat?
        #0x11 = on
        #0x13 = off
        #0x19 = light status info (in command2)
        #0x17 = light level manual change START
        #0x18 = light level manual change STOP
        if (isGrpCleanupAck or isGrpBroadcast) and command1 != 0x13 and command1 !=0x11 and command1 != 0x19:
            if command1 != 0x06 and command1 != 0x17: #don't ask for status on a heartbeat or the start of a manual change
                logger.debug("Running status request:{isGrpCleanupAck}:{isGrpBroadcast}:{isGrpCleanupDirect}",
                             isGrpCleanupAck=isGrpCleanupAck, isGrpBroadcast=isGrpBroadcast, isGrpCleanupDirect=isGrpCleanupDirect)
                self.lightStatusRequest(destDeviceId, async=True)
            else:
                logger.debug("Ignoring command: {command1}:{isGrpCleanupAck}:{isGrpBroadcast}:{isGrpCleanupDirect}:..........", command1=command1, isGrpCleanupAck=isGrpCleanupAck, isGrpBroadcast=isGrpBroadcast, isGrpCleanupDirect=isGrpCleanupDirect)
        else: # direct command

            self._logger.debug("Setting status for:{0}:{1}:{2}..........".format(
                                                                                 str(destDeviceId),
                                                                                 str(command1),
                                                                                 str(command2),
                                                                                 ))
            if self._devices:
                for d in self._devices:
                    if d.address.upper() == destDeviceId:
                        # only run the command if the state is different than current
                        if command1 == 0x13:
                            if d.state != State.OFF:
                                self._onCommand(address=destDeviceId, command=State.OFF)
                        elif command1 == 0x11:
                            if d.state != State.ON:
                                if d.verify_on_level:
                                    logger.debug('Received "On" command and "Verify On Level" set, sending status request for: {destDeviceId}..........', destDeviceI=destDeviceId)
                                    self.lightStatusRequest(destDeviceId, async=True)
                                else:
                                    self._onCommand(address=destDeviceId, command=State.ON)
                        elif d.state != (State.LEVEL, command2):
                            if command2 < 0x02: #Off -- Doesn't always go to 0
                                if d.state != State.OFF:
                                    self._onCommand(address=destDeviceId, command=State.OFF)
                            elif command2 > 0xFD: #On -- Doesn't always go to 255
                                if d.state != State.ON:
                                    self._onCommand(address=destDeviceId, command=State.ON)
                            else:
                                self._onCommand(address=destDeviceId, command=(State.LEVEL, int(command2 / 2.54)))
            else: # No devices to check state, so send anyway
                if command1 == 0x13:
                    if d.state != State.OFF:
                        self._onCommand(address=destDeviceId, command=State.OFF)
                elif command1 == 0x11:
                    if d.state != State.ON:
                        self._onCommand(address=destDeviceId, command=State.ON)
                elif command2:
                    if command2 < 0x02: #Off -- Doesn't always go to 0
                        self._onCommand(address=destDeviceId, command=State.OFF)
                    elif command2 > 0xFD: #On -- Doesn't always go to 255
                        self._onCommand(address=destDeviceId, command=State.ON)
                    else:
                        self._onCommand(address=destDeviceId, command=(State.LEVEL, int(command2 / 2.54)))

        self.statusRequest = False
        return (True,None)
        # Old stuff, don't use this at the moment
        #lightLevelRaw = messageBytes[10]
        #map the lightLevelRaw value to a sane value between 0 and 1
        #normalizedLightLevel = simpleMap(ord(lightLevelRaw), 0, 255, 0, 1)

        #return (True, {'lightStatus': round(normalizedLightLevel, 2) })

   	# _checkCommandQueue is run every iteration of _readInterface. It counts the commands 
    # to find repeating ones.  If a command is repeated too many times it means it never
    # received a response so we should delete the original command and delete it from the
    # queue.  This is a hack and will be dealt with properly in the new driver.
    def _checkCommandQueue(self):
        if self._pendingCommandDetails != {}:
            for (commandHash, commandDetails) in self._pendingCommandDetails.items():
                self.cmdQueueList.append(commandHash)
                
                # If we have an orphaned queue it will show up here, get the details, remove the old command
                # from the queue and re-issue.
                if self.cmdQueueList.count(commandHash) > 50:
                    if commandDetails['modemCommand'] in ['\x60','\x61','\x62']:
                        #print "deleting commandhash ", commandHash
                        #print commandDetails
                        cmd1 = commandDetails['commandId1']  # example SD11
                        cmd2 = commandDetails['commandId2']
                        deviceId = commandDetails['destinationDevice']
                        waitEvent = commandDetails['waitEvent']
                        waitEvent.set()
                        del self._pendingCommandDetails[commandHash]
                        while commandHash in self.cmdQueueList:
                            self.cmdQueueList.remove(commandHash)
                        # Retry the command..Do we really want this?
                        self._sendStandardP2PInsteonCommand(deviceId, cmd1[2:], cmd2)

    def __getattr__(self, name):
        name = name.lower()
        # Support levels of lighting
        if name[0] == 'l' and len(name) == 3:
            level = name[1:3]
            level = int((int(level) / 100.0) * int(0xFF))
            return lambda x, y=None: self.level(x, level, timeout=y ) 



    #---------------------------public methods---------------------------------
    
    def getPLMInfo(self, timeout = None):
        commandExecutionDetails = self._sendInterfaceCommand('60')

        return self._waitForCommandToFinish(commandExecutionDetails, timeout = timeout)

    # This doesn't work and ping in Insteon seems broken as far as I can tell.
    # The ping command 0x0D seems to return an ack from non-existant devices.
    def pingDevice(self, deviceId, timeout = None):
        startTime = time.time()
        commandExecutionDetails = self._sendStandardP2PInsteonCommand(deviceId, '0F', '00')

        #Wait for ping result
        commandReturnCode = self._waitForCommandToFinish(commandExecutionDetails, timeout = timeout)
        endTime = time.time()

        if commandReturnCode:
            return endTime - startTime
        else:
            return False

    def idRequest(self, deviceId, timeout = None):
        if len(deviceId) != 2: #insteon device address
            commandExecutionDetails = self._sendExtendedP2PInsteonCommand(deviceId, '10', '00', '0')
            return self._waitForCommandToFinish(commandExecutionDetails, timeout = timeout)
        return

    def getInsteonEngineVersion(self, deviceId, timeout = None):
        if len(deviceId) != 2: #insteon device address
            commandExecutionDetails = self._sendStandardP2PInsteonCommand(deviceId, '0D', '00')
            return self._waitForCommandToFinish(commandExecutionDetails, timeout = timeout)
        # X10 device,  command not supported,  just return
        return

    def getProductData(self, deviceId, timeout = None):
        if len(deviceId) != 2: #insteon device address
            commandExecutionDetails = self._sendStandardP2PInsteonCommand(deviceId, '03', '00', )
            return self._waitForCommandToFinish(commandExecutionDetails, timeout = timeout)
        # X10 device,  command not supported,  just return
        return

    def lightStatusRequest(self, deviceId, timeout = None, async = False):
        if len(deviceId) != 2: #insteon device address
            commandExecutionDetails = self._sendStandardP2PInsteonCommand(deviceId, '19', '00')
            if not async:
                return self._waitForCommandToFinish(commandExecutionDetails, timeout = timeout)
            return
        # X10 device,  command not supported,  just return
        return

    def relayStatusRequest(self, deviceId, timeout = None):
        if len(deviceId) != 2: #insteon device address
            commandExecutionDetails = self._sendStandardP2PInsteonCommand(deviceId, '19', '01')
            return self._waitForCommandToFinish(commandExecutionDetails, timeout = timeout)
        # X10 device,  command not supported,  just return
        return

    def command(self, incommingcommand, timeout=None):
        command = incommingcommand.command.lower()
        logger.warn("what: {what}", what = incommingcommand.dump())
        if incommingcommand.deviceobj.deviceClass == "insteon":
            commandExecutionDetails = self._sendStandardP2PInsteonCommand(incommingcommand.address, "%02x" % (self._command[command]['primary']['insteon']), "%02x" % (self._command[command]['secondary']['insteon']))
            logger.info("InsteonA" + commandExecutionDetails)
        elif incommingcommand.deviceobj.deviceClass == "x10":
            commandExecutionDetails = self._sendStandardP2PX10Command(address,"%02x" % (self._command[command]['primary']['x10']))
            logger.debug("X10A" + commandExecutionDetails)
        else:
            logger.warning("Unknown deviceclass: {deviceClass}", deviceClass=incommingcommand.deviceobj.deviceClass)
            return False
        return self._waitForCommandToFinish(commandExecutionDetails, timeout = timeout)

    def on(self, deviceId, fast=None, timeout = 2.5):
        if fast == 'fast':
            cmd = '12'
        else:
            cmd = '11'
        if len(deviceId) != 2: #insteon device address
            commandExecutionDetails = self._sendStandardP2PInsteonCommand(deviceId, cmd, 'ff')
        else: #X10 device address
            commandExecutionDetails = self._sendStandardP2PX10Command(deviceId,'02')
        return self._waitForCommandToFinish(commandExecutionDetails, timeout = timeout)

    def off(self, deviceId, fast=None, timeout = 2.5):
        if fast == 'fast':
            cmd = '14'
        else:
            cmd = '13'
        if len(deviceId) != 2: #insteon device address
            commandExecutionDetails = self._sendStandardP2PInsteonCommand(deviceId, cmd, '00')
        else: #X10 device address
            commandExecutionDetails = self._sendStandardP2PX10Command(deviceId,'03')
        return self._waitForCommandToFinish(commandExecutionDetails, timeout = timeout)
    
      
    # if rate the bits 0-3 is 2 x ramprate +1, bits 4-7 on level + 0x0F
    def level(self, deviceId, level, rate=None, timeout=None):
        if level > 100 or level <0:
            logger.error("{name} cannot set light level {level} beyond 1-15".format(
                                                                                    name=self.name,
                                                                                    level=level,
                                                                                     ))
            return
        else:
            if rate is None:
                # make it 0 to 255                                                                                     
                level = int((int(level) / 100.0) * int(0xFF))
                commandExecutionDetails = self._sendStandardP2PInsteonCommand(deviceId, '11', '%02x' % level)
                return self._waitForCommandToFinish(commandExecutionDetails, timeout=timeout)

            else:
                if rate > 15 or rate <1:
                    logger.error("{name} cannot set light ramp rate {rate} beyond 1-15".format(
                                                                                    name=self.name,
                                                                                    level=level,
                                                                                     ))
                    return
                else:
                    lev = int(simpleMap(level, 1, 100, 1, 15))                                                                                     
                    levelramp = (int(lev) << 4) + rate
                    commandExecutionDetails = self._sendStandardP2PInsteonCommand(deviceId, '2E', '%02x' % levelramp)
                    return self._waitForCommandToFinish(commandExecutionDetails, timeout=timeout)

   # # if rate the bits 0-3 is 2 x ramprate +1, bits 4-7 on level + 0x0F
   #  def level(self, deviceId, level, rate=None, timeout=None):
   #      if level > 100 or level <0:
   #          self._logger.error("{name} cannot set light level {level} beyond 1-15".format(
   #                                                                                  name=self.name,
   #                                                                                  level=level,
   #                                                                                   ))
   #          return
   #      else:
   #          if rate is None:
   #              # make it 0 to 255
   #              level = int((int(level) / 100.0) * int(0xFF))
   #              commandExecutionDetails = self._sendStandardP2PInsteonCommand(deviceId, '11', '%02x' % level)
   #              return self._waitForCommandToFinish(commandExecutionDetails, timeout=timeout)
   #
   #          else:
   #              if rate > 15 or rate <1:
   #                  self._logger.error("{name} cannot set light ramp rate {rate} beyond 1-15".format(
   #                                                                                  name=self.name,
   #                                                                                  level=level,
   #                                                                                   ))
   #                  return
   #              else:
   #                  lev = int(simpleMap(level, 1, 100, 1, 15))
   #                  levelramp = (int(lev) << 4) + rate
   #                  commandExecutionDetails = self._sendStandardP2PInsteonCommand(deviceId, '2E', '%02x' % levelramp)
   #                  return self._waitForCommandToFinish(commandExecutionDetails, timeout=timeout)

    def level_up(self, deviceId, timeout=None):
        if len(deviceId) != 2: #insteon device address
            commandExecutionDetails = self._sendStandardP2PInsteonCommand(deviceId, '15', '00')
            return self._waitForCommandToFinish(commandExecutionDetails, timeout=timeout)
        # X10 device,  command not supported,  just return
        return

    def level_down(self, deviceId, timeout=None):
        if len(deviceId) != 2: #insteon device address
            commandExecutionDetails = self._sendStandardP2PInsteonCommand(deviceId, '16', '00')
            return self._waitForCommandToFinish(commandExecutionDetails, timeout=timeout)
        # X10 device,  command not supported,  just return
        return

    def status(self, deviceId, timeout=None):
        if len(deviceId) != 2: #insteon device address
            return self.lightStatusRequest(deviceId, timeout, async=True)
        # X10 device,  command not supported,  just return
        return

    # Activate scene with the address passed
    def active(self, address, timeout=None):
        if len(address) != 2: #insteon device address
            commandExecutionDetails = self._sendStandardAllLinkInsteonCommand(address, '12', 'FF')
            return self._waitForCommandToFinish(commandExecutionDetails, timeout = timeout)
        # X10 device,  command not supported,  just return
        return

    def inactive(self, address, timeout=None):
        if len(address) != 2: #insteon device address
            commandExecutionDetails = self._sendStandardAllLinkInsteonCommand(address, '14', '00')
            return self._waitForCommandToFinish(commandExecutionDetails, timeout = timeout)
        # X10 device,  command not supported,  just return
        return

    def update_status(self):
        for d in self._devices:
            if len(d.address) == 8:  # real address not scene
                print "Getting status for ", d.address
                self.lightStatusRequest(d.address)

    def update_scene(self, address, devices):
        # we are passed a scene number to update and a bunch of objects to update
        for device in devices:
            for k, v in device.iteritems():
                print 'This is a device member' + str(k)
        
    def version(self):
        logger.info("Insteon Pytomation driver version " + self.VERSION)


#**********************************************************************************************
#
#   Experimental Insteon stuff
#
#-----------------------------------------------------------------------------------------------
    # yeah of course this doesn't work cause Insteon has 5 year olds writing it's software.
    def getAllProductData(self):
        for d in self._devices:
            if len(d.address) == 8:  # real address not scene
                print "Getting product data for ", d.address
                self.RgetProductData(d.address)
                time.sleep(2.0)

    def getAllIdRequest(self):
        for d in self._devices:
            if len(d.address) == 8:  # real address not scene
                print "Getting product data for ", d.address
                self.idRequest(d.address)
                time.sleep(2.0)


        

    def bitstring(self, s):
        return str(s) if s<=1 else self.bitstring(s>>1) + str(s&1)

    def _sendExtendedP2PInsteonCommand(self, destinationDevice, commandId1, commandId2, d1_d14):
        logger.debug("Extended Command: %s %s %s %s" % (destinationDevice, commandId1, commandId2, d1_d14))
        self.extendedCommand = True
        return self._sendInterfaceCommand('62', _stringIdToByteIds(destinationDevice) + _buildFlags(self.extendedCommand) + binascii.unhexlify(commandId1) + binascii.unhexlify(commandId2), extraCommandDetails = { 'destinationDevice': destinationDevice, 'commandId1': 'SD' + commandId1, 'commandId2': commandId2})
    
    def _process_InboundAllLinkRecordResponse(self, responseBytes):
        #print hex_dump(responseBytes)
        (modemCommand, insteonCommand, recordFlags, recordGroup, toIdHigh, toIdMid, toIdLow, linkData1, linkData2, linkData3) = struct.unpack('BBBBBBBBBB', responseBytes)
        #keep the prints commented, for example format only
        #print "Device    Group Flags     Data1 Data2 Data3"
        #print "------------------------------------------------"
        print "%02x.%02x.%02x  %02x    %s  %d    %d    %d" % (toIdHigh, toIdMid, toIdLow, recordGroup,self.bitstring(recordFlags),linkData1, linkData2, linkData3)

    def _process_InboundAllLinkCleanupStatusReport(self, responseBytes):
        if responseBytes[2] == '\x06':
            logger.debug("All-Link Cleanup completed...")
            foundCommandHash = None
            waitEvent = None
            for (commandHash, commandDetails) in self._pendingCommandDetails.items():
                if commandDetails['modemCommand'] == '\x61':
                    originatingCommandId1 = None
                
                    if commandDetails.has_key('commandId1'):  #example SD11
                        originatingCommandId1 = commandDetails['commandId1']  # = SD11

                    if commandDetails.has_key('commandId2'):  #example FF
                        originatingCommandId2 = commandDetails['commandId2']
                
                    destDeviceId = None
                    if commandDetails.has_key('destinationDevice'):
                        destDeviceId = commandDetails['destinationDevice']
                
                    waitEvent = commandDetails['waitEvent']
                    foundCommandHash = commandHash
                    break

        if foundCommandHash is None:
            logger.warn("Unhandled packet (couldn't find any pending command to deal with it)")
            logger.warn("This could be an unsolocicited broadcast message")

        if waitEvent and foundCommandHash:
            time.sleep(1.0)  # wait for a bit befor resending the command.
            waitEvent.set()
            del self._pendingCommandDetails[foundCommandHash]
            
        else:
            logger.debug("All-Link Cleanup received a NAK...")


    # The group command failed, lets dig out the original command and issue a direct
    # command to the failed device. we will also delete the original command from pendingCommandDetails.
    def _process_InboundAllLinkCleanupFailureReport(self, responseBytes):
        (modemCommand, insteonCommand, deviceGroup, toIdHigh, toIdMid, toIdLow) = struct.unpack('BBBBBB', responseBytes)
        logger.debug("All-Link Cleanup Failure, resending command after 1 second...")
        #find our pending command in the list so we can say that we're done (if we are running in syncronous mode - if not well then the caller didn't care)
        foundCommandHash = None
        waitEvent = None
        for (commandHash, commandDetails) in self._pendingCommandDetails.items():
            if commandDetails['modemCommand'] == '\x61':
                originatingCommandId1 = None
                
                if commandDetails.has_key('commandId1'):  #example SD11
                    originatingCommandId1 = commandDetails['commandId1']  # = SD11

                if commandDetails.has_key('commandId2'):  #example FF
                    originatingCommandId2 = commandDetails['commandId2']
                
                destDeviceId = _byteIdToStringId(toIdHigh, toIdMid, toIdLow)
                #destDeviceId = None
                #if commandDetails.has_key('destinationDevice'):
                #    destDeviceId = commandDetails['destinationDevice']
                
                waitEvent = commandDetails['waitEvent']
                foundCommandHash = commandHash
                break

        if foundCommandHash is None:
            logger.warn("Unhandled packet (couldn't find any pending command to deal with it)")
            logger.warn("All Link - This could be an unsolocicited broadcast message")

        if waitEvent and foundCommandHash:
            waitEvent.set()
            del self._pendingCommandDetails[foundCommandHash]
            #self._sendStandardAllLinkInsteonCommand(destDeviceId, originatingCommandId1[2:], originatingCommandId2)
            self._sendStandardP2PInsteonCommand(destDeviceId, originatingCommandId1[2:], originatingCommandId2)
            
        
    
    def print_linked_insteon_devices(self):
        print "Device    Group Flags     Data1 Data2 Data3"
        print "------------------------------------------------"
        self.request_first_all_link_record()
        while self.request_next_all_link_record():
            time.sleep(0.1)
            
    def getkeypad(self):
        destinationDevice='12.BD.CA'
        commandId1='2E'
        commandId2='00'
        d1_d14='0000000000000000000000000000'
        self.extendedCommand = True
        return self._sendInterfaceCommand('62', _stringIdToByteIds(destinationDevice) + '\x1F' + 
                binascii.unhexlify(commandId1) + binascii.unhexlify(commandId2) + binascii.unhexlify(d1_d14), 
                extraCommandDetails = { 'destinationDevice': destinationDevice, 'commandId1': 'SD' + commandId1, 
                'commandId2': commandId2})

        
    def request_first_all_link_record(self, timeout=None):
        commandExecutionDetails = self._sendInterfaceCommand('69')
        #print "Sending Command 0x69..."
        return self._waitForCommandToFinish(commandExecutionDetails, timeout = timeout)


    def request_next_all_link_record(self, timeout=None):
        commandExecutionDetails = self._sendInterfaceCommand('6A')
        #print "Sending Command 0x6A..."
        return self._waitForCommandToFinish(commandExecutionDetails, timeout = timeout)


    def hex_dump(self, src, length=8):
        N=0; result=''
        while src:
            s,src = src[:length],src[length:]
            hexa = ' '.join(["%02X"%ord(x) for x in s])
            ## {{{ http://code.activestate.com/recipes/142812/ (r1)
            filter=''.join([(len(repr(chr(x)))==3) and chr(x) or '.' for x in range(256)])
            s = s.translate(filter)
            result += "%04X   %-*s   %s\n" % (N, length*3, hexa, s)
            N+=length
        return result


class InsteonPLMSerialProtocol(Protocol):
    def __init__(self, factory):
        self._ModDescription = "Insteon PLM Serial/USB interface"
        self._ModAuthor = "Mitch Schwenk @ Yombo"
        self._ModUrl = "http://www.yombo.net"

        self.factory = factory  #insteon PLM module from above
        self.sendQueue = deque()
        self.__buffer = deque()
        self._sendDataDefer = None
        self.factory._serialProtocol = self

    def connectionFailed(self):
        logger.warn("Insteon connection failed!!")


    def connectionMade(self):
        logger.debug("Connected to Insteon PLM")
#        self.statusCheckTimer.start(15)
#        self.checkQueueTimer.start(150)

#    def sendStatusCheck(self):
#        self.sendLine("G00")  #say hello to homevision

    def dataReceived(self, newdata):
        self.__buffer.extend(list(newdata))
        print "@@@@@: %s" % self.__buffer
        if self._sendDataDefer != None:
            self._sendDataDefer.cancel()

        self._sendDataDefer = reactor.callLater(0.2, self.notifyData)

    def readData(self, numbytes):
        tempData = ''
        if len(self.__buffer) >= numbytes:
            for x in range(0,numbytes):
                tempData = tempData + self.__buffer.popleft()
        print "@!!!: %s" % self.__buffer
        return tempData

    def notifyData(self):
        tempBuffer = self.__buffer
        self._sendDataDefer = None
        self.factory._readInterface('')


    def send(self, data):
#        logger.debug("Sendline to homevision: %s", line)
        self.transport.write("data")

    
class Lookup(dict):
    """
    a dictionary which can lookup value by key, or keys by value
    # tested with Python25 by Ene Uran 01/19/2008    http://www.daniweb.com/software-development/python/code/217019
    """
    def __init__(self, items=[]):
        """items can be a list of pair_lists or a dictionary"""
        dict.__init__(self, items)

    def get_key(self, value):
        """find the key as a list given a value"""
        if type(value) == type(dict()):
            items = [item[0] for item in self.items() if item[1][value.items()[0][0]] == value.items()[0][1]]
        else:
            items = [item[0] for item in self.items() if item[1] == value]
        return items[0]

    def get_keys(self, value):
        """find the key(s) as a list given a value"""
        return [item[0] for item in self.items() if item[1] == value]

    def get_value(self, key):
        """find the value given a key"""
        return self[key]

