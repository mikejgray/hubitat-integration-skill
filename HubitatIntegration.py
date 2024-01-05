# pylint: disable=broad-exception-caught,missing-class-docstring,missing-module-docstring
import json
import socket
from typing import Any, Callable

from ovos_workshop.decorators import intent_handler
from ovos_workshop.skills import OVOSSkill
from ovos_bus_client.message import Message
from ovos_utils.parse import fuzzy_match, MatchStrategy
import requests

__author__ = "burnsfisher,GonzRon"


class HubitatIntegration(OVOSSkill):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.configured = False
        self.dev_commands_dict = {}
        self.settings_change_callback: Callable = lambda x: None
        self.name_dict_present: bool = False
        self.dev_id_dict = {}
        self.attr_dict = {}

    def initialize(self):
        """Initialize skill settings."""
        # This dict will hold the device name and its hubitat id number
        self.dev_id_dict = {}
        self.name_dict_present = False
        # Get a few settings from the Mycroft web site (they are specific to the user site) and
        # get the current values
        self.settings_change_callback = self.on_settings_changed
        self.on_settings_changed()

    @property
    def access_token(self) -> dict[str, Any]:
        """Retrieves the access_token property from settings.

        Returns:
            dict[str, Any]: access_token
        """
        return {"access_token": self.settings.get("access_token", "")}

    @property
    def address(self) -> str:
        """Retrieves the address property from settings.

        Returns:
            str: address
        """
        address = self.settings.get("local_address", "hubitat.local")
        # If the device name is local assume it is fairly slow and change it to a dotted quad
        try:
            address = socket.gethostbyname(address)
            socket.inet_aton(address)
            return address
        except socket.error:
            self.log.info(f"Invalid Hostname or IP Address: addr={address}")
            return "hubitat.local"

    @property
    def min_fuzz(self) -> int:
        """Retrieves the minimum_fuzzy_score property from settings.

        Returns:
            int: minimum_fuzzy_score
        """
        try:
            return int(self.settings.get("minimum_fuzzy_score", "50"))
        except ValueError:
            self.log.error(
                "Invalid minimum fuzzy score, must an integer, setting default to 50"
            )
            return 50

    @property
    def maker_api_app_id(self) -> str:
        """Retrieves the hubitat_maker_api_app_id property from settings.

        Returns:
            str: hubitat_maker_api_app_id
        """
        return self.settings.get("hubitat_maker_api_app_id", "")

    def on_settings_changed(self):
        """Updates the skill settings."""
        # The attributes are a special case.  I want to end up with a dict indexed by attribute
        # name with the contents being the default device.  But I did not want the user to have
        # to specify this in Python syntax.  So I just have the user give CSVs, possibly in quotes,
        # and the convert them to lists and then to a dict.
        attr_name = self.settings.get("attr_name", "")
        dev_name = self.settings.get("dev_name", "")
        self.log.debug(
            f"Address={self.address},token={self.access_token},app id={self.maker_api_app_id}"
        )

        if all(
            [
                self.access_token,
                self.address,
                self.min_fuzz,
                self.maker_api_app_id,
                attr_name,
                dev_name,
            ]
        ):
            # Remove quotes
            attr_name: str = attr_name.replace('"', "").replace("'", "")
            dev_name: str = dev_name.replace('"', "").replace("'", "")
            self.log.debug(f"Settings are {attr_name} and {dev_name}")

            # Turn them into lists
            attrs = attr_name.rsplit(",")
            devs = dev_name.rsplit(",")
            # self.log.info("Changed to "+attrs+" and "+devs)

            # Now turn the two lists into a dict and add an attribute for testing
            self.attr_dict = dict(zip(attrs, devs))
            self.attr_dict["testattr"] = "testAttrDev"
            self.log.debug(self.attr_dict)

            self.log.debug(
                f"Updated settings: access token={self.access_token}, fuzzy={self.min_fuzz}, addr={self.address}, "
                f"makerApiId={self.maker_api_app_id}, attr dictionary={self.attr_dict}"
            )
            self.configured = True

    def not_configured(self):
        """Speak a dialog and log an error"""
        self.log.debug("Cannot Run Intent - Settings not Configured")

    #
    # Intent handlers
    #

    @intent_handler("turn.on.intent")
    def handle_on_intent(self, message: Message):
        '''This is for utterances like "turn on the xxx"'''
        if self.configured:
            self.handle_on_or_off_intent(message, "on")
        else:
            self.not_configured()

    @intent_handler("turn.off.intent")
    def handle_off_intent(self, message: Message):
        """For utterances like "turn off the xxx"."""
        if self.configured:
            self.handle_on_or_off_intent(message, "off")
        else:
            self.not_configured()

    @intent_handler("level.intent")
    def handle_level_intent(self, message: Message):
        '''For utterances like "set the xxx to yyy%"'''
        if self.configured:
            device = ""
            try:
                device = self.get_hub_device_name(message)
            except Exception as err:
                # g_h_d_n speaks a dialog before throwing an error
                self.log.error(err)
                return

            level = message.data.get("level")
            supported_modes = [
                s.strip()
                for s in self.hub_get_attribute(
                    self.hub_get_device_id(device), "supportedThermostatModes"
                )
                .strip("[]")
                .split(",")
                if isinstance(s, str)
            ]
            self.log.debug("Set Level Supported Modes: " + str(supported_modes))
            self.log.debug("Level is: " + str(level))

            if not device:
                self.log.error("No Device passed in utterance!")
                return
            if level in supported_modes:
                if self.is_command_available(
                    command="setThermostatMode", device=device
                ):
                    self.hub_command_devices(
                        self.hub_get_device_id(device), "setThermostatMode", level
                    )
                else:
                    self.not_configured()
            elif self.is_command_available(command="setLevel", device=device):
                self.hub_command_devices(
                    self.hub_get_device_id(device), "setLevel", level
                )
                self.speak_dialog("ok", data={"device": device})
        else:
            self.not_configured()

    @intent_handler("attr.intent")
    def handle_attr_intent(self, message: Message):
        """For getting device attributes like level or temperature"""
        if self.configured:
            try:
                attr: str = self.hub_get_attr_name(message.data.get("attr", ""))
            except Exception as err:
                # Get_attr_name also speaks before throwing an error
                self.log.error(err)
                return
            try:
                device = self.get_hub_device_name(message)
            except Exception as err:
                self.log.warning(
                    f"Error getting device name: {err}, trying to get device from attribute name"
                )
                device = self.get_hub_device_name_from_text(self.attr_dict[attr])

            self.log.debug(f"Found attribute={attr},device={device}")
            val = self.hub_get_attribute(self.hub_get_device_id(device), attr)
            if val is None:
                self.speak_dialog(
                    "attr.not.supported", data={"device": device, "attr": attr}
                )
            else:
                self.speak_dialog(
                    "attr", data={"device": device, "attr": attr, "value": val}
                )
        else:
            self.not_configured()

    @intent_handler("rescan.intent")
    def handle_rescan_intent(self, _):
        """Retrieve a new list of devices from Hubitat"""
        if self.configured:
            count = self.update_devices()
            self.log.info(str(count))
            self.speak_dialog("rescan", data={"count": count})
        else:
            self.not_configured()

    @intent_handler("list.devices.intent")
    def handle_list_devices_intent(self, _):
        """List the devices that are known to Hubitat and speak them aloud"""
        if self.configured:
            if not self.name_dict_present:
                self.update_devices()
            number = 0
            for hub_dev, ident in self.dev_id_dict.items():
                # Speak the real devices, but not the test devices
                if ident[0:6] != "**test":
                    number = number + 1
                    self.speak_dialog(
                        "list.devices",
                        data={"number": str(number), "name": hub_dev, "id": ident},
                    )
        else:
            self.not_configured()

    #
    # Routines used by intent handlers
    #
    def handle_on_or_off_intent(self, message: Message, cmd):
        """Used for both on and off"""
        try:
            self.log.debug("In on/off intent with command " + cmd)
            device = self.get_hub_device_name(message)
            silence = message.data.get("how")
        except Exception as err:
            # get_hub_device_name speaks the error dialog
            self.log.error(err)
            return

        if self.is_command_available(command=cmd, device=device):
            try:
                self.hub_command_devices(self.hub_get_device_id(device), cmd)
                if silence is None:
                    self.speak_dialog("ok", data={"device": device})
            except Exception as error:
                self.log.error(f"Error on command, probably a bad URL: {error}")
                # If command devices throws an error, probably a bad URL
                self.speak_dialog("url.error")

    def is_command_available(self, device, command):
        """Complain if the specified attribute is not one in the Hubitat maker app."""
        if not self.dev_commands_dict:
            self.update_devices()
        for real_dev, commands in self.dev_commands_dict.items():
            if device.find(real_dev) >= 0 and command in commands:
                return True
        self.speak_dialog(
            "command.not.supported", data={"device": device, "command": command}
        )
        return False

    def get_hub_device_name(self, message: Message):
        """This one looks in an utterance message for 'device' and then passes the text to
        get_hub_device_name_from_text to see if it is in Hubitat
        """
        self.log.debug("In get_h_d_n with device=")
        utt_device = message.data.get("device")
        self.log.debug(utt_device)
        if utt_device is None:
            self.log.error("No Device passed in utterance!")
        device_name = self.get_hub_device_name_from_text(utt_device)
        self.log.debug("Device is " + str(device_name))
        return device_name

    def get_hub_device_name_from_text(self, text):
        """Look for a device name in the list of Hubitat devices.
        The text may have something a bit different than the real name like "the light" or "lights" rather
        than the actual Hubitat name of light.  This finds the actual Hubitat name using fuzzy search and
        the match score specified as a setting by the user (default of 50)
        """
        if not self.name_dict_present:
            # In case we never got the devices
            self.update_devices()

        # Here we compare all the Hubitat devices against the requested device using fuzzy and take
        # the device with the highest score that exceeds the minimum
        best_name = None
        best_score = self.min_fuzz
        for hub_dev in self.dev_id_dict:
            score = fuzzy_match(hub_dev, text, MatchStrategy.TOKEN_SORT_RATIO)
            self.log.debug(
                "Hubitat=" + hub_dev + ", utterance=" + text + " score=" + str(score)
            )
            if score > best_score:
                best_score = score
                best_name = hub_dev
        self.log.debug("Best score is " + str(best_score))
        if best_score > self.min_fuzz:
            self.log.debug("Changed " + text + " to " + best_name)
            return best_name

        # Nothing had a high enough score.  Speak and throw.
        self.log.debug("No device found for " + text)
        self.speak_dialog("device.not.supported", data={"device": text})
        self.log.error("Unsupported Device")

    def hub_get_device_id(self, device):
        """devIds is a dict with the device name from hubitat as the key, and the ID number as the value.
        This returns the ID number to send to hubitat
        """
        for hub_dev, hub_id in self.dev_id_dict.items():
            # self.log.debug("hubDev:"+hubDev+" device="+device)
            if device.find(hub_dev) >= 0:
                self.log.debug("Found device I said: " + hub_dev + " ID=" + hub_id)
                return hub_id
        return ""

    def hub_get_attr_name(self, name) -> str:
        """This is why we need a list of possible attributes.  Otherwise we could not do a fuzzy search."""
        best_name = ""
        best_score = self.min_fuzz
        self.log.debug(self.attr_dict)
        attr = ""

        for attribute, _ in self.attr_dict.items():
            self.log.debug(f"attr is {attribute}")
            score = fuzzy_match(attr, name, MatchStrategy.TOKEN_SORT_RATIO)
            # self.log.info("Hubitat="+hubDev+", utterance="+text+" score="+str(score))
            if score > best_score:
                best_score = score
                best_name = attribute

        self.log.debug("Best score is " + str(best_score))
        if best_score > self.min_fuzz:
            self.log.debug("Changed " + attr + " to " + best_name)
            return best_name
        else:
            self.log.debug("No device found for " + name)
            self.speak_dialog(
                "attr.not.supported",
                data={"device": "any device in settings", "attr": name},
            )
            self.log.error(f"Unsupported Attribute for {name}")
        return ""

    def hub_command_devices(self, dev_id, state, value=None):
        """Build a URL to send the requested command to the Hubitat and
        send it via "access_hubitat".  Some commands also have a value like "setlevel"
        """
        if dev_id[0:6] == "**test":
            # This is used for regression tests only
            return
        url = (
            "/apps/api/" + self.maker_api_app_id + "/devices/" + dev_id + "/" + state
        )  # This URL is as specified in Hubitat maker app
        if value:
            url = url + "/" + value
        self.log.debug("URL for switching device " + url)
        self.access_hubitat(url)

    def hub_get_attribute(self, dev_id, attr):
        """Get the value of the specified attribute from the specified device."""
        self.log.debug(f"Looking for attr {attr}")
        # The json string from Hubitat turns into a dict.  The key attributes
        # has a value of a list.  The list is a list of dicts with the attribute
        # name, value, and other things that we don't care about.  So here when
        # the device was a test device, we fake out the attributes for testing
        if dev_id == "**testAttr":
            temp_list = [{"name": "testattr", "currentValue": 99}]
            jsn = {"attributes": temp_list}
            x = jsn["attributes"]
        else:
            # Here we get the real json string from hubitat
            url = "/apps/api/" + self.maker_api_app_id + "/devices/" + dev_id
            ret_val = self.access_hubitat(url)
            jsn = json.loads(ret_val)
            self.log.debug(jsn)
        # Now we have a nested set of dicts and lists as described above, either a simple
        # one for test or the real (and more complex) one for a real Hubitat

        for info in jsn:
            if info == "attributes":
                for ret_attr in jsn[info]:
                    if ret_attr["name"] == attr:
                        self.log.debug(
                            "Found Attribute Match: "
                            + str(ret_attr.get("currentValue"))
                        )
                        return ret_attr.get("currentValue", "")
        return ""

    def update_devices(self):
        """Get the list of devices from Hubitat and parse out the device names and IDs and valid commands."""
        json_data = {}
        this_label = ""
        this_id = ""
        # Init the device list and command list with tests
        self.dev_commands_dict = {
            "testOnDev": ["on"],
            "testOnOffDev": ["on", "off"],
            "testLevelDev": ["on", "off", "setLevel"],
        }
        self.dev_id_dict = {
            "testOnDev": "**testOnOff",
            "testOnOffDev": "**testOnOff",
            "testLevelDev": "**testLevel",
            "testAttrDev": "**testAttr",
        }
        self.log.debug(self.access_token)

        # Now get the actual devices from Hubitat and parse out the devices and their IDs and valid
        # commands
        request = self.access_hubitat(
            "/apps/api/" + self.maker_api_app_id + "/devices/all"
        )

        if (
            not request
            or request.find("AppException") != -1
            or request.find("invalid_token") != -1
        ):
            self.speak_dialog("url.error")
            self.log.debug("Bad returns from get all devices")
            return 0
        try:
            json_data = json.loads(request)
        except Exception as err:
            self.log.debug(f"Error on json load:\n{err}")
        count = 0
        for device in json_data:
            # For every device returned, record as a dict the id to use in a URL and the label to be spoken
            # thisId = device.items()['id']
            # thisLabel = device.items()['label']
            # self.log.info("Id is "+str(thisId)+"label is "+thisLabel)
            for k, v in device.items():
                self.log.debug("attribute is " + str(k) + " value is " + str(v))
                if k == "id":
                    this_id = v
                elif k == "label":
                    this_label = v
                    self.dev_commands_dict[this_label] = []
                elif k == "commands":
                    self.log.debug("Commands for " + this_label + " is=>" + str(v))
                    for cmd in v:
                        self.dev_commands_dict[this_label].append(cmd["command"])
            self.dev_id_dict[this_label] = this_id
            self.log.debug(self.dev_commands_dict[this_label])
            count = count + 1
        self.name_dict_present = True
        return count

    def access_hubitat(self, part_url: str):
        """This routine knows how to talk to the hubitat.  It builds the URL from
        the known access type (http://) and the domain info or dotted quad in
        self.address, followed by the command info passed in by the caller.
        """
        request = requests.Response()
        url = "http://" + self.address + part_url
        try:
            request = requests.get(url, params=self.access_token, timeout=5)
        except Exception as err:
            self.log.warning(f"Error on request, will try to find new IP:\n{err}")
            # If the request throws an error, the address may have changed.  Try
            # 'hubitat.local' as a backup.
            try:
                self.speak_dialog("url.backup")
                self.settings["address"] = socket.gethostbyname("hubitat.local")
                url = "http://" + self.address + part_url
                self.log.debug(
                    "Fell back to hubitat.local which translated to " + self.address
                )
                request = requests.get(url, params=self.access_token, timeout=10)
            except Exception as error:
                self.log.warning(f"Got an error from requests:\n{error}")
                self.log.debug("Got an error from requests")
                self.speak_dialog("url.error")
        return request.text if request else ""
