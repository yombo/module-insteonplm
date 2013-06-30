#This file was created by Yombo for use with Yombo Gateway automation
#software.  Details can be found at http://www.yombo.net
"""
Insteon PLM
===========

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
the Free Software Foundation, either version 3 of the License, or
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
:copyright: Copyright 2012 by Yombo.
:license: GPL(v3)
:organization: `Yombo <http://www.yombo.net>`_
"""
from collections import deque
import binascii
import hashlib
import struct
from serial.serialutil import SerialException

from twisted.internet import utils, reactor
from twisted.internet.task import LoopingCall
from twisted.internet.protocol import Protocol
from twisted.internet.serialport import SerialPort

from yombo.core.module import YomboModule
from yombo.core.log import getLogger
from yombo.core.helpers import getComponent
from yombo.core.log import getLogger

logger = getLogger()

class InsteonPLM(YomboModule):
    """
    The primary class...
    """

    def init(self):
        self._ModDescription = "Insteoin command interface"
        self._ModAuthor = "Mitch Schwenk @ Yombo"
        self._ModUrl = "http://www.yombo.net"

        self.HVSerial = None

        self.startable = False # track when load has completed...

        self.pending = False
        self.queue = deque()
        self.checkQueueLoop = LoopingCall(self.checkQueue)

        self.__modemCommands = {'60': {
                                    'responseSize':7,
                                    'callBack':self.__process_PLMInfo
                                  },
                                '62': {
                                    'responseSize':7,
                                    'callBack':self.__process_StandardInsteonMessagePLMEcho
                                  },
                                  
                                '50': {
                                    'responseSize':9,
                                    'callBack':self.__process_InboundStandardInsteonMessage
                                  },
                                '51': {
                                    'responseSize':23,
                                    'callBack':self.__process_InboundExtendedInsteonMessage
                                  },                                
                                '63': {
                                    'responseSize':4,
                                    'callBack':self.__process_StandardX10MessagePLMEcho
                                  },
                                '52': {
                                    'responseSize':4,
                                    'callBack':self.__process_InboundX10Message
                                 },
                            }
        
        self.__insteonCommands = {
                                    #Direct Messages/Responses
                                    'SD03': {        #Product Data Request (generally an Ack)                            
                                        'callBack' : self.__handle_StandardDirect_IgnoreAck
                                    },
                                    'SD0D': {        #Get InsteonPLM Engine                            
                                        'callBack' : self.__handle_StandardDirect_EngineResponse,
                                        'validResponseCommands' : ['SD0D']
                                    },
                                    'SD0F': {        #Ping Device                        
                                        'callBack' : self.__handle_StandardDirect_AckCompletesCommand,
                                        'validResponseCommands' : ['SD0F']
                                    },
                                    'SD10': {        #ID Request    (generally an Ack)                        
                                        'callBack' : self.__handle_StandardDirect_IgnoreAck,
                                        'validResponseCommands' : ['SD10', 'SB01']
                                    },    
                                    'SD11': {        #Devce On                                
                                        'callBack' : self.__handle_StandardDirect_AckCompletesCommand,
                                        'validResponseCommands' : ['SD11']
                                    },                                    
                                    'SD12': {        #Devce On Fast                                
                                        'callBack' : self.__handle_StandardDirect_AckCompletesCommand,
                                        'validResponseCommands' : ['SD12']
                                    },                                    
                                    'SD13': {        #Devce Off                                
                                        'callBack' : self.__handle_StandardDirect_AckCompletesCommand,
                                        'validResponseCommands' : ['SD13']
                                    },                                    
                                    'SD14': {        #Devce Off Fast                                
                                        'callBack' : self.__handle_StandardDirect_AckCompletesCommand,
                                        'validResponseCommands' : ['SD14']                                    
                                    },
                                    'SD15': {        #Brighten one step
                                        'callBack' : self.__handle_StandardDirect_AckCompletesCommand,
                                        'validResponseCommands' : ['SD15']                                    
                                    },    
                                    'SD16': {        #Dim one step
                                        'callBack' : self.__handle_StandardDirect_AckCompletesCommand,
                                        'validResponseCommands' : ['SD16']                                    
                                    },                                
                                    'SD19': {        #Light Status Response                                
                                        'callBack' : self.__handle_StandardDirect_LightStatusResponse,
                                        'validResponseCommands' : ['SD19']
                                    },    
                                    #Broadcast Messages/Responses                                
                                    'SB01': {    
                                                    #Set button pushed                                
                                        'callBack' : self.__handle_StandardBroadcast_SetButtonPressed
                                    },                                   
                                }
        
        self.__x10HouseCodes = Lookup(zip((
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
        
        self.__x10UnitCodes = Lookup(zip((
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
        
        self._allLinkDatabase = dict()
        
#        self.__interfaceRunningEvent = false
        
#        self.__commandLock = threading.Lock()
#        self.__outboundCommandDetails = dict()
#        self.__retryCount = dict()        
        
#        self.__pendingCommandDetails = dict()        
        
#        self.__commandReturnData = dict()
        
#        self.__intersend_delay = 0.15 #150 ms between network sends
#        self.__lastSendTime = 0

#        print "Using %s for PLM communication" % serialDevicePath
#       self.__serialDevice = serial.Serial(serialDevicePath, 19200, timeout = 0.1)     
#        self.__interface = interface    

        self.__pendingCommandDetails = dict() 
        self.__incomingPending = False
        self.__running = False
        self.__loaded = False
        self.__lastPacketHash = None
        self._buffer = ''

        self._attempts = 0
        self._interval = 3
        self._baudrate = '19200'
        self._connected = False
        self._hasStarted = False # true if self.start has been called

    def load(self):
        self.APIModule = getComponent("yombo.gateway.modules.InsteonAPI")
        logger.debug("######== %s", self._ModVariables);


#        PLMAddress = self._Modvariables[""][""]
        self.PLMType = "serial"
        self.PLMAddress = self._ModVariables['devLocation'][0]
#        self.PLMAddress = '/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A600HTUE-if00-port0'

#todo: convert to exception
        if self.PLMAddress == None:
            logger.error("InsteonPLM cannot load, PLM address empty.")
            return
        return self._startConnection()
        
    def _startConnection(self):
        """
        Make the actual connection to the PLM device..
        """
        if self.PLMType == "serial":
            try:
                self.PLM = SerialPort(InsteonPLMSerialProtocol(self), self.PLMAddress, reactor, self._baudrate)
                self._connected = True
            except SerialException, error:
                self._attempts += 1
                if self._attempts % 10 ==1:
                    logger.warning("Unable to connect to InsteonPLM serial port. Will continue trying. Attempt: %d, Reason: %s", self._attempts, error)
                reactor.callLater(self._interval, self._startConnection)
        else:
            self.PLM = SerialPort(InsteonPLMSerialProtocol(self), self.PLMAddress, reactor, self._baudrate)
            self._connected = True
            if self._hasStarted == True:  #check if we are behind on startup.
                self.checkQueueLoop.start(2)
        self.__running = True
        self.__loaded = True


    def start(self):
        self._hasStarted = True
        if self._connected == True:
            self.checkQueueLoop.start(2)

    def stop(self):
        pass

    def unload(self):
        self.__loaded = False
        
        self.__running = False
        return

    def sendInsteonCmd(self, insteoncmdID):
        """
        Commands from Insteon API come into here. They need to be processed
        and sent to interface.
        """
#        logger.debug("x10cmds: %s", self.APIModule.x10cmds)
        insteonCmd = self.APIModule.insteoncmds[insteoncmdID]
        
#        logger.debug("x10hey cmd/type house/number: %s/%s %s/%d" % (command['cmd'], command['type'], house, number))


    def _compileCMD(self, insteonCmd):
        
        command = insteonCmd.insteoncommand.lower()
        if insteonCmd.devicetype == 'insteon':
            logger.debug("InsteonA")
            commandExecutionDetails = self.__sendStandardP2PInsteonCommand(insteonCmd.insteonaddress, "%02x" % (HACommand()[command]['primary']['insteon']), "%02x" % (HACommand()[command]['secondary']['insteon']))
        elif insteonCmd.devicetype == 'insteon':
            logger.debug("X10A")
            commandExecutionDetails = self.__sendStandardP2PX10Command(insteonCmd.insteonaddress,"%02x" % (HACommand()[command]['primary']['x10']))
        else:
            logger.debug("compileCMD...Invalid device type.")
        self._addQueue()
        return self.__waitForCommandToFinish(commandExecutionDetails, timeout = timeout)            
        

    def connected(self):
        """
        Called by the interface protocol once connected..
        """
        pass


    ####  Commands
    def turnOn(self, deviceId, timeout = None):        
        if len(deviceId) != 2: #insteon device address
            commandExecutionDetails = self.__sendStandardP2PInsteonCommand(deviceId, '11', 'ff')                        
        else: #X10 device address
            commandExecutionDetails = self.__sendStandardP2PX10Command(deviceId,'02')
        return self.__waitForCommandToFinish(commandExecutionDetails, timeout = timeout)            

    def turnOff(self, deviceId, timeout = None):
        if len(deviceId) != 2: #insteon device address
            commandExecutionDetails = self.__sendStandardP2PInsteonCommand(deviceId, '13', '00')
        else: #X10 device address
            commandExecutionDetails = self.__sendStandardP2PX10Command(deviceId,'03')
        return self.__waitForCommandToFinish(commandExecutionDetails, timeout = timeout) 


    def _byteIdToStringId(self, idHigh, idMid, idLow):
        return '%02X.%02X.%02X' % (idHigh, idMid, idLow)

    def checkQueue(self):
        if self.pending == False:
            if len(self.queue) > 0:
                self.pending = True
                newitem = self.queue.pop()
                self._send(newitem)

    def recievePLM(self, newdata):
        self.__incomingPending = True
#        logger.debug("Received something from PLM: %s", self.hex_dump(newdata))
        
        self._buffer = self._buffer + newdata

        data = []
        for c in self._buffer:
            d = binascii.b2a_hex(c)
#            d = binascii.b2a_hex(c).upper()
#            logger.debug("character: %s", d)
            data.append(d)
            
        working = True
        while working:
            if len(data) > 2:
                logger.debug("1: %s", data)
                if self._buffer[0] == '\x02':

                    responseSize = -1
                    callBack = None

                    modemCommand = data[1]
                    if self.__modemCommands.has_key(modemCommand):
                        if self.__modemCommands[modemCommand].has_key('responseSize'):                                                                    
                            responseSize = self.__modemCommands[modemCommand]['responseSize']                            
                        if self.__modemCommands[modemCommand].has_key('callBack'):                                                                    
                            callBack = self.__modemCommands[modemCommand]['callBack']                            

                    if responseSize != -1:                        
                        if len(self._buffer) >= responseSize+2:
                            logger.debug("2: %s", data)
                            logger.debug("have large enough response size")

#                            logger.debug("< %s  (%d)", self.hex_dump(self._buffer[2:responseSize+2]), len(self._buffer[2:responseSize+2]))
                            currentPacketHash = self._hashPacket(self._buffer[2:responseSize+2])
                            logger.debug("chash: %s, lasthash: %s", currentPacketHash, self.__lastPacketHash)
                            if self.__lastPacketHash and self.__lastPacketHash == currentPacketHash:
                                logger.debug("Ignoring last packet...")
                                pass
                            else:                        
                                if callBack:
                                    callBack(self._buffer[:responseSize+2])    
                                else:
                                    logger.debug("No callBack defined for for modem command %s" % modemCommand)

                            self.__lastPacketHash = currentPacketHash    

                            #trim the buffer and data to remove processed packet.
                            self._buffer = self._buffer[responseSize+2:]  
                            data = data[responseSize+2:]  
                        else:
                            logger.debug("Not enought buffer inside of response size. Required: %d, Size: %d", responseSize+2, len(self._buffer))
                            working = False
                    else:
                        print "No responseSize defined for modem command %s" % modemCommand                        
                        self._buffer = self._buffer[2:]  
                        data = data[2:]  
                elif firstByte[0] == '\x15':
                    print "Received a Modem NAK!"
                else:
                    print "Unknown first byte %s" % binascii.hexlify(firstByte[0])
                    self._buffer = self._buffer[1:]  
                    data = data[1:]  
            else:
                logger.debug("Not enough data yet. waiting.")
                working = False
                    
        self.checkQueue()    

    def _hashPacket(self, packetData):
        return hashlib.md5(packetData).hexdigest()

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

    def _send(self, newitem):
        self.pending = True
        logger.debug("heyu sending: %s", newitem['args'])
        output = utils.getProcessValue('/usr/local/bin/heyu', newitem['args'] )
        output.addCallback(self._sendCallback, newitem['x10cmdID'])

    def _sendCallback(self, val, x10cmdID=None):
        self.pending = False
        logger.debug("!!!!Heyu callback val: %s" % val)
        if x10cmdID != None:
            self.APIModule.x10cmds[x10cmdID].cmdDone()
        self.checkQueue()


    #low level processing methods
    def __process_PLMInfo(self, responseBytes):                
        (modemCommand, idHigh, idMid, idLow, deviceCat, deviceSubCat, firmwareVer, acknak) = struct.unpack('xBBBBBBBB', responseBytes)        
        
        foundCommandHash = None        
        #find our pending command in the list so we can say that we're done (if we are running in syncronous mode - if not well then the caller didn't care)
        for (commandHash, commandDetails) in self.__pendingCommandDetails.items():                        
            if binascii.unhexlify(commandDetails['modemCommand']) == chr(modemCommand):
                #Looks like this is our command.  Lets deal with it.                
                self.__commandReturnData[commandHash] = { 'id': _byteIdToStringId(idHigh,idMid,idLow), 'deviceCategory': '%02X' % deviceCat, 'deviceSubCategory': '%02X' % deviceSubCat, 'firmwareVersion': '%02X' % firmwareVer }    
                
                waitEvent = commandDetails['waitEvent']
                waitEvent.set()
                
                foundCommandHash = commandHash
                break
                
        if foundCommandHash:
            del self.__pendingCommandDetails[foundCommandHash]
        else:
            print "Unable to find pending command details for the following packet:"
            print hex_dump(responseBytes, len(responseBytes))
            
    def __process_StandardInsteonMessagePLMEcho(self, responseBytes):                
        #print utilities.hex_dump(responseBytes, len(responseBytes))
        #we don't do anything here.  Just eat the echoed bytes
        pass
            
    def __process_StandardX10MessagePLMEcho(self, responseBytes):
        # Just ack / error echo from sending an X10 command
        pass
        
    def __validResponseMessagesForCommandId(self, commandId):
        if self.__insteonCommands.has_key(commandId):
            commandInfo = self.__insteonCommands[commandId]
            if commandInfo.has_key('validResponseCommands'):
                return commandInfo['validResponseCommands']
        
        return False
        
    def __testBit(self, int_type, offset):
        mask = 1 << offset
        if (int_type & mask) > 0:
            return 1
        else:
            return 0
        return(int_type & mask)

    def __process_InboundStandardInsteonMessage(self, responseBytes):
        (insteonCommand, fromIdHigh, fromIdMid, fromIdLow, toIdHigh, toIdMid, toIdLow, messageFlags, command1, command2) = struct.unpack('xBBBBBBBBBB', responseBytes)        
        
        foundCommandHash = None            
        waitEvent = None
        
        logger.debug(insteonCommand)
        logger.debug(messageFlags)
        logger.debug(self.__testBit(messageFlags, 7))
        logger.debug(self.__testBit(messageFlags, 6))
        logger.debug(self.__testBit(messageFlags, 5))
        logger.debug(self.__testBit(messageFlags, 4))
        logger.debug(self.__testBit(messageFlags, 3))
        logger.debug(self.__testBit(messageFlags, 2))
        logger.debug(self.__testBit(messageFlags, 1))
        logger.debug(self.__testBit(messageFlags, 0))
        
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
            
        if insteonCommandCode == 'SD00':
            #this is a strange special case...
            #lightStatusRequest returns a standard message and overwrites the cmd1 and cmd2 bytes with "data"
            #cmd1 (that we use here to sort out what kind of incoming message we got) contains an 
            #"ALL-Link Database Delta number that increments every time there is a change in the addressee's ALL-Link Database"
            #which makes is super hard to deal with this response (cause cmd1 can likley change)
            #for now my testing has show that its 0 (at least with my dimmer switch - my guess is cause I haven't linked it with anything)
            #so we treat the SD00 message special and pretend its really a SD19 message (and that works fine for now cause we only really
            #care about cmd2 - as it has our light status in it)
            insteonCommandCode = 'SD19'
        
        logger.debug("insteonCommandCode = %s", insteonCommandCode)
        
        #find our pending command in the list so we can say that we're done (if we are running in syncronous mode - if not well then the caller didn't care)
        for (commandHash, commandDetails) in self.__pendingCommandDetails.items():
            
            #since this was a standard insteon message the modem command used to send it was a 0x62 so we check for that
            if binascii.unhexlify(commandDetails['modemCommand']) == '\x62':                                                                        
                originatingCommandId1 = None
                if commandDetails.has_key('commandId1'):
                    originatingCommandId1 = commandDetails['commandId1']    
                    
                validResponseMessages = self.__validResponseMessagesForCommandId(originatingCommandId1)
                if validResponseMessages and len(validResponseMessages):
                    #Check to see if this received command is one that this pending command is waiting for
                    if validResponseMessages.count(insteonCommandCode) == 0:
                        #this pending command isn't waiting for a response with this command code...  Move along
                        continue
                else:
                    print "Unable to find a list of valid response messages for command %s" % originatingCommandId1
                    continue
                        
                    
                #since there could be multiple insteon messages flying out over the wire, check to see if this one is from the device we send this command to
                destDeviceId = None
                if commandDetails.has_key('destinationDevice'):
                    destDeviceId = commandDetails['destinationDevice']
                        
                if destDeviceId:
                    if destDeviceId == _byteIdToStringId(fromIdHigh, fromIdMid, fromIdLow):
                                                                        
                        returnData = {} #{'isBroadcast': isBroadcast, 'isDirect': isDirect, 'isAck': isAck}
                        
                        #try and look up a handler for this command code
                        if self.__insteonCommands.has_key(insteonCommandCode):
                            if self.__insteonCommands[insteonCommandCode].has_key('callBack'):
                                (requestCycleDone, extraReturnData) = self.__insteonCommands[insteonCommandCode]['callBack'](responseBytes)
                                                        
                                if extraReturnData:
                                    returnData = dict(returnData.items() + extraReturnData.items())
                                
                                if requestCycleDone:                                    
                                    waitEvent = commandDetails['waitEvent']                                    
                            else:
                                print "No callBack for insteon command code %s" % insteonCommandCode    
                        else:
                            print "No insteonCommand lookup defined for insteon command code %s" % insteonCommandCode    
                                
                        if len(returnData):
                            self.__commandReturnData[commandHash] = returnData
                                                                                                                
                        foundCommandHash = commandHash
                        break
            
        if foundCommandHash == None:
            print "Unhandled packet (couldn't find any pending command to deal with it)"
            print "This could be an unsolocicited broadcast message %s" % toIdHigh
#            , fromIdMid, fromIdLow, toIdHigh, toIdMid, toIdLow
        if waitEvent and foundCommandHash:
            waitEvent.set()            
            del self.__pendingCommandDetails[foundCommandHash]
            
            print "Command %s completed" % foundCommandHash
    
    def __process_InboundExtendedInsteonMessage(self, responseBytes):
        #51 
        #17 C4 4A     from
        #18 BA 62     to
        #50         flags
        #FF         cmd1
        #C0         cmd2
        #02 90 00 00 00 00 00 00 00 00 00 00 00 00    data
        (insteonCommand, fromIdHigh, fromIdMid, fromIdLow, toIdHigh, toIdMid, toIdLow, messageFlags, command1, command2, data) = struct.unpack('xBBBBBBBBBB14s', responseBytes)        
        
        pass
        
    def __process_InboundX10Message(self, responseBytes):        
        "Receive Handler for X10 Data"
        #X10 sends commands fully in two separate messages. Not sure how to handle this yet
        #TODO not implemented
        unitCode = None
        commandCode = None
        print "X10> ", hex_dump(responseBytes, len(responseBytes)),
 #       (insteonCommand, fromIdHigh, fromIdMid, fromIdLow, toIdHigh, toIdMid, toIdLow, messageFlags, command1, command2) = struct.unpack('xBBBBBBBBBB', responseBytes)        
#        houseCode =     (int(responseBytes[4:6],16) & 0b11110000) >> 4 
 #       houseCodeDec = X10_House_Codes.get_key(houseCode)
#        keyCode =       (int(responseBytes[4:6],16) & 0b00001111)
#        flag =          int(responseBytes[6:8],16)
        
        
                
    #insteon message handlers
    def __handle_StandardDirect_IgnoreAck(self, messageBytes):
        #just ignore the ack for what ever command triggered us
        #there is most likley more data coming for what ever command we are handling
        return (False, None)
        
    def __handle_StandardDirect_AckCompletesCommand(self, messageBytes):
        #the ack for our command completes things.  So let the system know so
        return (True, None)                            
                                                    
    def __handle_StandardBroadcast_SetButtonPressed(self, messageBytes):        
        #02 50 17 C4 4A 01 19 38 8B 01 00
        (idHigh, idMid, idLow, deviceCat, deviceSubCat, deviceRevision) = struct.unpack('xxBBBBBBxxx', messageBytes)
        return (True, {'deviceType': '%02X%02X' % (deviceCat, deviceSubCat), 'deviceRevision':'%02X' % deviceRevision})
            
    def __handle_StandardDirect_EngineResponse(self, messageBytes):        
        #02 50 17 C4 4A 18 BA 62 2B 0D 01        
        engineVersionIdentifier = messageBytes[10]            
        return (True, {'engineVersion': engineVersionIdentifier == '\x01' and 'i2' or 'i1'})
            
    def __handle_StandardDirect_LightStatusResponse(self, messageBytes):
        #02 50 17 C4 4A 18 BA 62 2B 00 00
        lightLevelRaw = messageBytes[10]    
        
        #map the lightLevelRaw value to a sane value between 0 and 1
        normalizedLightLevel = simpleMap(ord(lightLevelRaw), 0, 255, 0, 1)
                    
        return (True, {'lightStatus': round(normalizedLightLevel, 2) })


class InsteonPLMSerialProtocol(Protocol):
    def __init__(self, factory):
        self._ModDescription = "Insteon PLM Serial/USB interface"
        self._ModAuthor = "Mitch Schwenk @ Yombo"
        self._ModUrl = "http://www.yombo.net"

        self.factory = factory  #homevision module from above

    def connectionFailed(self):
        logger.warning("Insteon connection failed!!")
        self

    def connectionMade(self):
        logger.debug("Connected to Insteon PLM")
#        self.statusCheckTimer.start(15)
#        self.checkQueueTimer.start(150)

    def sendStatusCheck(self):
        self.sendLine("G00")  #say hello to homevision

    def dataReceived(self, newdata):
        self.factory.recievePLM(newdata)

    def send(self, data):
#        logger.trace("Sendline to homevision: %s", line)
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
    
class HACommand(Lookup):
    def __init__(self):
        super(HACommand,self).__init__({
          'on'     :{'primary' : {
                       'insteon':0x11,
                       'x10':0x02
                       }, 
                    'secondary' : {
                       'insteon':0xff,
                       'x10':None
                       },
                    },
          'faston' :{'primary' : {
                       'insteon':0x12,
                       'x10':0x02
                       }, 
                     'secondary' : {
                       'insteon':0xff,
                       'x10':None
                       },
                    },
          'off'    :{'primary' : {
                       'insteon':0x13,
                       'x10':0x03
                       }, 
                     'secondary' : {
                       'insteon':0x00,
                       'x10':None
                       },
                    },
          'fastoff':{'primary' : {
                       'insteon':0x14,
                       'x10':0x03
                       }, 
                     'secondary' : {
                       'insteon':0x00,
                       'x10':None
                       },
                    },
          'level'  :{'primary' : {
                       'insteon':0x11,
                       'x10':0x0a
                       }, 
                     'secondary' : {
                       'insteon':None,
                       'x10':None
                       },
                     },
          'brighten':{'primary' : {
                       'insteon':0x15,
                       'x10':0x0a
                       }, 
                     'secondary' : {
                       'insteon':None,
                       'x10':None
                       },
                    },
          'dim'    :{'primary' : {
                       'insteon':0x16,
                       'x10':0x0a
                       }, 
                     'secondary' : {
                       'insteon':None,
                       'x10':None
                       },
                     },
          } )
        pass

class HADevice(object):
    def __init__(self,deviceId,interface = None):
        super(HADevice,self).__init__()
        self.interface = interface
        self.deviceId = deviceId
        
    def set(self, command):
        self.interface.command(self, command)
    
class InsteonDevice(HADevice):
    def __init__(self, deviceId, interface = None):
        super(InsteonDevice, self).__init__(deviceId, interface)

class X10Device(HADevice):    
    def __init__(self, deviceId, interface = None):
        super(X10Device, self).__init__(deviceId, interface)
