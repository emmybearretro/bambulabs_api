__all__ = ["PrinterMQTTClient"]

import json
import logging
import ssl
import datetime
from typing import Any, Callable
from re import match

import paho.mqtt.client as mqtt
import paho.mqtt.properties
import paho.mqtt.reasoncodes
from paho.mqtt.enums import CallbackAPIVersion

from bambulabs_api.ams import AMS, AMSHub
from bambulabs_api.printer_info import NozzleType

from .filament_info import Filament, FilamentTray
from .states_info import GcodeState, PrintStatus


def is_valid_gcode(line: str):
    """
    Check if a line is a valid G-code command

    Args:
        line (str): The line to check

    Returns:
        bool: True if the line is a valid G-code command, False otherwise
    """
    # Remove whitespace and comments
    line = line.split(";")[0].strip()

    # Check if line is empty or starts with a valid G-code command (G or M)
    if not line or not match(r"^[GM]\d+", line):
        return False

    # Check for proper parameter formatting
    tokens = line.split()
    for token in tokens[1:]:
        if not match(r"^[A-Z]-?\d+(\.\d+)?$", token):
            return False

    return True


class PrinterMQTTClient:
    """
    Printer class for handling MQTT communication with the printer
    """

    def __init__(
            self,
            hostname: str,
            access: str,
            printer_serial: str,
            username: str = "bblp",
            port: int = 8883,
            timeout: int = 60,
            pushall_timeout: int = 60,
            pushall_on_connect: bool = True,
            strict: bool = False,
    ):
        self._hostname = hostname
        self._access = access
        self._username = username
        self._printer_serial = printer_serial

        self._port = port
        self._timeout = timeout

        self._client: mqtt.Client = mqtt.Client(
            CallbackAPIVersion.VERSION2,
            protocol=mqtt.MQTTv311,
        )
        self._client.username_pw_set(username, access)
        self._client.tls_set(  # type: ignore
            tls_version=ssl.PROTOCOL_TLS,
            cert_reqs=ssl.CERT_NONE
        )
        self._client.tls_insecure_set(True)

        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

        self.pushall_timeout: int = pushall_timeout
        self.pushall_aggressive = pushall_on_connect
        self._last_update: int = 0

        self.command_topic = f"device/{printer_serial}/request"
        logging.info(f"{self.command_topic}")   # noqa: E501  # pylint: disable=logging-fstring-interpolation
        self._data: dict[Any, Any] = {}

        self.ams_hub: AMSHub = AMSHub()
        self.strict = strict

    @staticmethod
    def __ready(func: Callable[..., Any]) -> Callable[..., Any]:  # noqa # pylint: disable=missing-function-docstring, no-self-argument
        def wrapper(
                self: 'PrinterMQTTClient',
                *args: list[Any],
                **kwargs: dict[str, Any]) -> Any:
            if not self.ready():
                logging.error("Printer Values Not Available Yet")

                if self.strict:
                    raise Exception("Printer not found")
            return func(self, *args, **kwargs)  # noqa # pylint: disable=not-callable
        return wrapper

    def ready(self) -> bool:
        return bool(self._data)

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: Any,
        msg: mqtt.MQTTMessage
    ) -> None:  # pylint: disable=unused-argument  # noqa
        # Current date and time
        doc = json.loads(msg.payload)
        self.manual_update(doc)

    def manual_update(self, doc: dict[str, Any]) -> None:
        if "print" in doc:
            self._data |= doc["print"]
            logging.debug(self._data)

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.ConnectFlags,
        rc: paho.mqtt.reasoncodes.ReasonCode,
        properties: paho.mqtt.properties.Properties | None
    ) -> None:  # pylint: disable=unused-argument
        """
        _on_connect Callback function for when the client
        receives a CONNACK response from the server.

        Parameters
        ----------
        client : mqtt.Client
            The client instance for this callback
        userdata : String
            User data
        flags : Arraylike
            Response flags sent by the broker
        rc : int
            The connection result
        """
        logging.info(f"Connection result code: {rc}")
        if rc == 0 or not rc.is_failure:
            logging.info("Connected successfully")
            client.subscribe(f"device/{self._printer_serial}/report")
            if self.pushall_aggressive:
                self._client.publish(
                    self.command_topic, json.dumps(
                        {"pushing": {"command": "pushall"}}))
            logging.info("Connection Handshake Completed")
        else:
            logging.warning(f"Connection failed with result code {rc}")

    def connect(self) -> None:
        """
        Connects to the MQTT server asynchronously
        """
        self._client.connect_async(self._hostname, self._port, self._timeout)

    def start(self):
        """
        Starts the MQTT client

        Returns:
            MQTTErrorCode: error code of loop start
        """
        return self._client.loop_start()

    def loop_forever(self):
        """
        Loop client forever (synchonous, blocking call)

        Returns:
            MQTTErrorCode: error code of loop start
        """
        return self._client.loop_forever()

    def stop(self):
        """
        Stops the MQTT client
        """
        self._client.loop_stop()

    def dump(self) -> dict[Any, Any]:
        """
        Dump the current state of the printer message

        Returns:
            dict[Any, Any]: The latest data recorded
        """
        return self._data

    @__ready
    def __get(self, key: str, default: Any = None) -> Any:
        self._update()
        return self._data.get(key, default)

    def _update(self) -> bool:
        current_time = int(datetime.datetime.now().timestamp())
        if self._last_update + self.pushall_timeout > current_time:
            return False
        self._last_update = current_time
        return self.pushall()

    def pushall(self) -> bool:
        """
        Force the printer to send a full update of the current state
        Warning: Pushall should be used sparingly - large numbers of updates
        can result in the printer lagging.

        Returns:
            bool: success state of the pushall command
        """
        return self.__publish_command({"pushing": {"command": "pushall"}})

    def get_last_print_percentage(self) -> int | str | None:
        """
        Get the last print percentage

        Returns:
            int | str | None: The last print percentage
        """
        return self.__get("mc_percent", None)

    def get_remaining_time(self) -> int | str | None:
        """
        Get the remaining time for the print

        Returns:
            int | str | None: The remaining time for the print
        """
        return self.__get("mc_remaining_time", None)

    def get_sequence_id(self):
        """
        Get the current sequence ID

        Returns:
            int : Get the current sequence ID
        """
        return int(self.__get("sequence_id", 0))

    def get_printer_state(self) -> GcodeState:
        """
        Get the printer state

        Returns:
            GcodeState: gcode state
        """
        return GcodeState(self.__get("gcode_state", -1))

    def get_file_name(self) -> str:
        """
        Get the file name of the current/last print

        Returns:
            str: file name
        """
        return self.__get("gcode_file", "")

    def get_print_speed(self) -> int:
        """
        Get the print speed

        Returns:
            int: print speed
        """
        return int(self.__get("spd_mag", 100))

    def __publish_command(self, payload: dict[Any, Any]) -> bool:
        """
        Generate a command payload and publish it to the MQTT server

        Args:
            payload (dict[Any, Any]): command to send to the printer
        """
        if self._client.is_connected() is False:
            logging.error("Not connected to the MQTT server")
            return False

        command = self._client.publish(self.command_topic, json.dumps(payload))
        logging.info(f"Published command: {payload}")   # noqa  # pylint: disable=logging-fstring-interpolation
        command.wait_for_publish()
        return command.is_published()

    def turn_light_off(self) -> bool:
        """
        Turn off the printer light
        """
        return self.__publish_command({"system": {"led_mode": "off"}})

    def turn_light_on(self) -> bool:
        """
        Turn on the printer light
        """
        return self.__publish_command({"system": {"led_mode": "on"}})

    def get_light_state(self) -> str:
        """
        Get the printer light state

        Returns:
            str: led_mode
        """
        light_report: list[dict[str, str]] = self.__get(
            "lights_report", [])

        if not light_report:
            return "unknown"

        return light_report[0].get("mode", "unknown")

    def start_print_3mf(self, filename: str,
                        plate_number: int,
                        bed_leveling: bool = True,
                        flow_calibration: bool = False,
                        vibration_calibration: bool = False,
                        bed_type:str = "textured_plate",
                        use_ams: bool = True,
                        ams_mapping: list[int] = [0],
                        skip_objects: list[int] | None = None,
                        ) -> bool:
        """
        Start the print

        Parameters:
            filename (str): The name of the file to print
            plate_number (int): The plate number to print to
            use_ams (bool, optional): Use the AMS system. Defaults to True.
            ams_mapping (list[int], optional): The AMS mapping. Defaults to
                [0].
            skip_objects (list[int] | None, optional): List of gcode objects to
                skip. Defaults to [].

        Returns:
            str: print_status
        """
        if skip_objects is not None and not skip_objects:
            skip_objects = None

        return self.__publish_command(
            {
                "print":
                    {
                        "command": "project_file",
                        "param": f"Metadata/plate_{int(plate_number)}.gcode",
                        "file": filename,
                        "bed_leveling": bed_leveling,
                        "bed_type": bed_type,
                        "flow_cali": flow_calibration,
                        "vibration_cali": vibration_calibration,
                        "url": f"ftp:///{filename}",
                        "layer_inspect": False,
                        "sequence_id": "10000000",
                        "use_ams": bool(use_ams),
                        "ams_mapping": list(ams_mapping),
                        "skip_objects": skip_objects,
                    }
            })


    def start_print_3mf_min(self, filename: str,
                        plate_number: int,
                        use_ams: bool = True,
                        ams_mapping: list[int] = [0],
                        skip_objects: list[int] | None = None,
                        ) -> bool:
        """
        Start the print

        Parameters:
            filename (str): The name of the file to print
            plate_number (int): The plate number to print to
            use_ams (bool, optional): Use the AMS system. Defaults to True.
            ams_mapping (list[int], optional): The AMS mapping. Defaults to
                [0].
            skip_objects (list[int] | None, optional): List of gcode objects to
                skip. Defaults to [].

        Returns:
            str: print_status
        """
        if skip_objects is not None and not skip_objects:
            skip_objects = None

        return self.__publish_command(
            {
                "print":
                {
                    "command": "project_file",
                    "param": f"Metadata/plate_{int(plate_number)}.gcode",
                    "file": filename,
                    "bed_leveling": True,
                    "bed_type": "textured_plate",
                    "flow_cali": True,
                    "vibration_cali": True,
                    "url": f"ftp:///{filename}",
                    "layer_inspect": False,
                    "sequence_id": "10000000",
                    "use_ams": bool(use_ams),
                    "ams_mapping": list(ams_mapping),
                    "skip_objects": skip_objects,
                }
            })

    def skip_objects(self, obj_list: list[int]) -> bool:
        """
        Skip Objects during printing.

        Args:
            obj_list (list[int]): object list to skip objects.

        Returns:
            bool: if publish command is successful
        """
        return self.__publish_command(
            {
                "print":
                {
                    "command": "skip_objects",
                    "obj_list": obj_list,
                }
            })

    def get_skipped_objects(self) -> list[int]:
        """
        Get skipped Objects.

        Args:

        Returns:
            bool: if publish command is successful
        """
        return self.__get("s_obj", [])

    def get_current_state(self) -> PrintStatus:
        """
        Get the current printer state from stg_cur

        Returns:
            PrintStatus: current_state
        """
        return PrintStatus(self.__get("stg_cur", -1))

    def stop_print(self) -> bool:
        """
        Stop the print

        Returns:
            str: print_status
        """
        return self.__publish_command({"print": {"command": "stop"}})

    def pause_print(self) -> bool:
        """
        Pause the print

        Returns:
            str: print_status
        """
        if self.get_printer_state() == GcodeState.PAUSE:
            return True
        return self.__publish_command({"print": {"command": "pause"}})

    def resume_print(self) -> bool:
        """
        Resume the print

        Returns:
            str: print_status
        """
        if self.get_printer_state() == GcodeState.RUNNING:
            return True
        return self.__publish_command({"print": {"command": "resume"}})

    def __send_gcode_line(self, gcode_command: str) -> bool:
        """
        Send a G-code line command to the printer

        Args:
            gcode_command (str): G-code command to send to the printer
        """
        return self.__publish_command({"print": {"command": "gcode_line",
                                                 "param": f"{gcode_command}"}})

    def send_gcode(self, gcode_command: str | list[str]) -> bool:
        """
        Send a G-code line command to the printer

        Args:
            gcode_command (str | list[str]): G-code command(s) to send to the
                printer
        """
        if isinstance(gcode_command, str):
            if not is_valid_gcode(gcode_command):
                raise ValueError("Invalid G-code command")

            return self.__send_gcode_line(gcode_command)
        elif isinstance(gcode_command, list):  # type: ignore
            if any(not is_valid_gcode(g) for g in gcode_command):
                raise ValueError("Invalid G-code command")
            return self.__send_gcode_line("\n".join(gcode_command))

    def set_bed_temperature(self, temperature: int) -> bool:
        """
        Set the bed temperature

        Args:
            temperature (int): The temperature to set the bed to

        Returns:
            bool: success of setting the bed temperature
        """
        return self.__send_gcode_line(f"M140 S{temperature}\n")

    def set_part_fan_speed(self, speed: int | float) -> bool:
        """
        Set the fan speed of the part fan

        Args:
            speed (int | float): The speed to set the part fan

        Returns:
            bool: success of setting the fan speed
        """
        return self._set_fan_speed(speed, 1)

    def set_aux_fan_speed(self, speed: int | float) -> bool:
        """
        Set the fan speed of the aux part fan

        Args:
            speed (int | float): The speed to set the part fan

        Returns:
            bool: success of setting the fan speed
        """
        return self._set_fan_speed(speed, 2)

    def set_chamber_fan_speed(self, speed: int | float) -> bool:
        """
        Set the fan speed of the chamber fan

        Args:
            speed (int | float): The speed to set the part fan

        Returns:
            bool: success of setting the fan speed
        """
        return self._set_fan_speed(speed, 3)

    def _set_fan_speed(self, speed: int | float, fan_num: int) -> bool:
        """
        Set the fan speed of a fan

        Args:
            speed (int | float): The speed to set the fan to
            fan_num (int): Id of the fan to be set

        Returns:
            bool: success of setting the fan speed
        """
        if isinstance(speed, int):
            if speed > 255 or speed < 0:
                raise ValueError(f"Fan Speed {speed} is not between 0 and 255")
            return self.__send_gcode_line(f"M106 P{fan_num} S{speed}\n")

        elif isinstance(speed, float):  # type: ignore
            if speed < 0 or speed > 1:
                raise ValueError(f"Fan Speed {speed} is not between 0 and 1")
            speed = round(255 / speed)
            return self.__send_gcode_line(f"M106 P{fan_num} S{speed}\n")

        raise ValueError("Fan Speed is not float or int")

    def set_bed_height(self, height: int) -> bool:
        """
        Set the absolute height of the bed (Z-axis).
        0 is the bed at the nozzle tip and 256 is the bed at the bottom of the printer.

        Args:
            height (int): height to set the bed to

        Returns:
            bool: success of the bed height setting
        """  # noqa
        return self.__send_gcode_line(f"G90\nG0 Z{height}\n")

    def auto_home(self) -> bool:
        """
        Auto home the printer

        Returns:
            bool: success of the auto home command
        """
        return self.__send_gcode_line("G28\n")

    def set_auto_step_recovery(self, auto_step_recovery: bool = True) -> bool:
        """
        Set whether or not to set auto step recovery

        Args:
            auto_step_recovery (bool): flag to set auto step recovery.
                Default True.

        Returns:
            bool: success of the auto step recovery command command
        """
        return self.__publish_command({"print": {
            "command": "gcode_line", "auto_recovery": auto_step_recovery
        }})

    def set_print_speed_lvl(self, speed_lvl: int = 1) -> bool:
        """
        Set the print speed

        Args:
            speed_lvl (int, optional): Set the speed level of printer. Defaults to 1.

        Returns:
            bool: success of setting the print speed
        """  # noqa
        return self.__publish_command(
            {"print": {"command": "print_speed", "param": f"{speed_lvl}"}}
        )

    def set_nozzle_temperature(self, temperature: int) -> bool:
        """
        Set the nozzle temperature

        Args:
            temperature (int): temperature to set the nozzle to

        Returns:
            bool: success of setting the nozzle temperature
        """
        return self.__send_gcode_line(f"M104 S{temperature}\n")

    def set_printer_filament(
        self,
        filament_material: Filament,
        colour: str,
        ams_id: int = 255,
        tray_id: int = 254,
    ) -> bool:
        """
        Set the printer filament manually fed into the printer

        Args:
            filament_material (Filament): filament material to set.
            colour (str): colour of the filament.
            ams_id (int): ams id. Default to external filament spool: 255.
            tray_id (int): tray id. Default to external filament spool: 254.

        Returns:
            bool: success of setting the printer filament
        """
        assert len(colour) == 6, "Colour must be a 6 character hex string"

        return self.__publish_command(
            {
                "print": {
                    "command": "ams_filament_setting",
                    "ams_id": ams_id,
                    "tray_id": tray_id,
                    "tray_info_idx": filament_material.tray_info_idx,
                    "tray_color": f"{colour.upper()}FF",
                    "nozzle_temp_min": filament_material.nozzle_temp_min,
                    "nozzle_temp_max": filament_material.nozzle_temp_max,
                    "tray_type": filament_material.tray_type
                }
            }
        )

    def load_filament_spool(self) -> bool:
        """
        Load the filament into the printer

        Returns:
            bool: success of loading the filament
        """
        return self.__publish_command(
            {
                "print": {
                    "command": "ams_change_filament",
                    "target": 255,
                    "curr_temp": 215,
                    "tar_temp": 215,
                }
            }
        )

    def unload_filament_spool(self) -> bool:
        """
        Unload the filament from the printer

        Returns:
            bool: success of unloading the filament
        """
        return self.__publish_command(
            {
                "print": {
                    "command": "ams_change_filament",
                    "target": 254,
                    "curr_temp": 215,
                    "tar_temp": 215,
                }
            }
        )

    def resume_filament_action(self) -> bool:
        """
        Resume the current filament action

        Returns:
            bool: success of resuming the filament action
        """
        return self.__publish_command(
            {
                "print": {
                    "command": "ams_control",
                    "param": "resume",
                }
            }
        )

    def calibration(
            self,
            bed_levelling: bool = True,
            motor_noise_cancellation: bool = True,
            vibration_compensation: bool = True) -> bool:
        """
        Start the full calibration process

        Returns:
            bool: success of starting the full calibration process
        """
        bitmask = 0

        if bed_levelling:
            bitmask |= 1 << 1
        if vibration_compensation:
            bitmask |= 1 << 2
        if motor_noise_cancellation:
            bitmask |= 1 << 3

        return self.__publish_command(
            {
                "print": {
                    "command": "calibration",
                    "option": bitmask
                }
            }
        )

    def get_bed_temperature(self) -> float:
        """
        Get the bed temperature

        Returns:
            float: bed temperature
        """
        return float(self.__get("bed_temper", 0.0))

    def get_bed_temperature_target(self) -> float:
        """
        Get the bed temperature target

        Returns:
            float: bed temperature target
        """
        return float(self.__get("bed_target_temper", 0.0))

    def get_nozzle_type(self) -> str:
        """
        Get the nozzle type

        Returns:
            str: nozzle type
        """
        i = 1
        return str(self.__get("nozzle_type", ""))

    def get_nozzle_diameter(self) -> float:
        """
        Get the nozzle diameter

        Returns:
            float: nozzle diameter
        """
        return float(self.__get("nozzle_diameter", 0.0))

    def get_nozzle_temperature(self) -> float:
        """
        Get the nozzle temperature

        Returns:
            float: nozzle temperature
        """
        return float(self.__get("nozzle_temper", 0.0))

    def get_nozzle_temperature_target(self) -> float:
        """
        Get the nozzle temperature target

        Returns:
            float: nozzle temperature target
        """
        return float(self.__get("nozzle_target_temper", 0.0))

    def current_layer_num(self) -> int:
        """
        Get the number of layers of the current/last print

        Returns:
            int: number of layers
        """
        return int(self.__get("layer_num", 0))

    def total_layer_num(self) -> int:
        """
        Get the total number of layers of the current/last print

        Returns:
            int: number of layers
        """
        return int(self.__get("total_layer_num", 0))

    def gcode_file_prepare_percentage(self) -> int:
        """
        Get the gcode file preparation percentage

        Returns:
            int: percentage
        """
        return int(self.__get("gcode_file_prepare_percent", 0))

    def nozzle_diameter(self) -> float:
        """
        Get the nozzle diameter currently registered to printer

        Returns:
            float: nozzle diameter
        """
        return float(self.__get("nozzle_diameter", 0))

    def nozzle_type(self) -> NozzleType:
        """
        Get the nozzle type currently registered to printer

        Returns:
            str: nozzle diameter
        """
        return NozzleType(self.__get("nozzle_diameter", "stainless_steel"))

    def process_ams(self):
        """
        Get the filament information from the AMS system
        """
        ams_info: dict[str, Any] = self.__get("ams")

        self.ams_hub = AMSHub()
        if not ams_info or ams_info.get("ams_exist_bits", "0") == "0":
            return

        ams_units: list[dict[str, Any]] = ams_info.get("ams", [])

        for k, v in enumerate(ams_units):
            humidity = int(v.get("humidity", 0))
            temp = float(v.get("temp", 0.0))
            id = int(v.get("id", k))

            ams = AMS(humidity=humidity, temperature=temp)

            trays: list[dict[str, Any]] = v.get("tray", [])

            if trays:
                for tray_id, tray in enumerate(trays):
                    tray_id = int(tray.get("id", tray_id))
                    tray_n: Any | None = tray.get("n", None)
                    if tray_n:
                        ams.set_filament_tray(
                            tray_index=tray_id,
                            filament_tray=FilamentTray.from_dict(tray))

            self.ams_hub[id] = ams

    def vt_tray(self) -> FilamentTray:
        """
        Get Filament Tray of the external spool.

        Returns:
            FilamentTray: External Spool Filament Tray
        """
        tray = self.__get("vt_tray")
        return FilamentTray.from_dict(tray)

    def get_nozzle_temperature(self) -> float:
        """
        Get the current nozzle temperature.

        Returns:
            float: Nozzle temperature in degrees Celsius.
        """
        return float(self.__get("nozzle_temper", 0.0))

    def get_nozzle_target_temperature(self) -> float:
        """
        Get the target nozzle temperature.

        Returns:
            float: Target nozzle temperature in degrees Celsius.
        """
        return float(self.__get("nozzle_target_temper", 0.0))

    def get_bed_temperature(self) -> float:
        """
        Get the current bed temperature.

        Returns:
            float: Bed temperature in degrees Celsius.
        """
        return float(self.__get("bed_temper", 0.0))

    def get_bed_target_temperature(self) -> float:
        """
        Get the target bed temperature.

        Returns:
            float: Target bed temperature in degrees Celsius.
        """
        return float(self.__get("bed_target_temper", 0.0))

    def get_chamber_temperature(self) -> float:
        """
        Get the current chamber temperature.

        Returns:
            float: Chamber temperature in degrees Celsius.
        """
        return float(self.__get("chamber_temper", 0.0))

    def get_print_stage(self) -> str:
        """
        Get the current print stage.

        Returns:
            str: Current print stage.
        """
        return str(self.__get("mc_print_stage", ""))

    def get_heatbreak_fan_speed(self) -> str:
        """
        Get the heatbreak fan speed.

        Returns:
            str: Heatbreak fan speed.
        """
        return str(self.__get("heatbreak_fan_speed", "0"))

    def get_cooling_fan_speed(self) -> str:
        """
        Get the cooling fan speed.

        Returns:
            str: Cooling fan speed.
        """
        return str(self.__get("cooling_fan_speed", "0"))

    def get_big_fan1_speed(self) -> str:
        """
        Get the speed of big fan 1.

        Returns:
            str: Speed of big fan 1.
        """
        return str(self.__get("big_fan1_speed", "0"))

    def get_big_fan2_speed(self) -> str:
        """
        Get the speed of big fan 2.

        Returns:
            str: Speed of big fan 2.
        """
        return str(self.__get("big_fan2_speed", "0"))

    def get_print_percentage(self) -> int:
        """
        Get the percentage of the print completed.

        Returns:
            int: Percentage of print completion.
        """
        return int(self.__get("mc_percent", 0))

    def get_remaining_print_time(self) -> int:
        """
        Get the remaining time for the print in seconds.

        Returns:
            int: Remaining time for the print.
        """
        return int(self.__get("mc_remaining_time", 0))

    def get_ams_status(self) -> int:
        """
        Get the AMS status.

        Returns:
            int: AMS status code.
        """
        return int(self.__get("ams_status", 0))

    def get_ams_rfid_status(self) -> int:
        """
        Get the AMS RFID status.

        Returns:
            int: AMS RFID status code.
        """
        return int(self.__get("ams_rfid_status", 0))

    def get_hardware_switch_state(self) -> int:
        """
        Get the hardware switch state.

        Returns:
            int: Hardware switch state.
        """
        return int(self.__get("hw_switch_state", 0))

    def get_print_speed_level(self) -> int:
        """
        Get the print speed level.

        Returns:
            int: Print speed level.
        """
        return int(self.__get("spd_lvl", 0))

    def get_print_error(self) -> int:
        """
        Get the print error status.

        Returns:
            int: Print error status.
        """
        return int(self.__get("print_error", 0))

    def get_lifecycle(self) -> str:
        """
        Get the lifecycle status of the printer.

        Returns:
            str: Lifecycle status.
        """
        return str(self.__get("lifecycle", ""))

    def get_wifi_signal(self) -> str:
        """
        Get the WiFi signal strength.

        Returns:
            str: WiFi signal strength.
        """
        return str(self.__get("wifi_signal", ""))

    def get_gcode_state(self) -> str:
        """
        Get the current G-code state.

        Returns:
            str: G-code state.
        """
        return str(self.__get("gcode_state", ""))

    def get_gcode_file_prepare_percentage(self) -> int:
        """
        Get the percentage of the G-code file preparation completed.

        Returns:
            int: G-code file preparation percentage.
        """
        return int(self.__get("gcode_file_prepare_percent", 0))

    def get_queue_number(self) -> int:
        """
        Get the current number in the print queue.

        Returns:
            int: Queue number.
        """
        return int(self.__get("queue_number", 0))

    def get_queue_total(self) -> int:
        """
        Get the total number of items in the print queue.

        Returns:
            int: Total queue items.
        """
        return int(self.__get("queue_total", 0))

    def get_queue_estimated_time(self) -> int:
        """
        Get the estimated time for the queue in seconds.

        Returns:
            int: Estimated queue time.
        """
        return int(self.__get("queue_est", 0))

    def get_queue_status(self) -> int:
        """
        Get the status of the queue.

        Returns:
            int: Queue status.
        """
        return int(self.__get("queue_sts", 0))

    def get_project_id(self) -> str:
        """
        Get the current project ID.

        Returns:
            str: Project ID.
        """
        return str(self.__get("project_id", ""))

    def get_profile_id(self) -> str:
        """
        Get the current profile ID.

        Returns:
            str: Profile ID.
        """
        return str(self.__get("profile_id", ""))

    def get_task_id(self) -> str:
        """
        Get the current task ID.

        Returns:
            str: Task ID.
        """
        return str(self.__get("task_id", ""))

    def get_subtask_id(self) -> str:
        """
        Get the current subtask ID.

        Returns:
            str: Subtask ID.
        """
        return str(self.__get("subtask_id", ""))

    def get_subtask_name(self) -> str:
        """
        Get the name of the current subtask.

        Returns:
            str: Subtask name.
        """
        return str(self.__get("subtask_name", ""))

    def get_gcode_file(self) -> str:
        """
        Get the name of the G-code file currently in use.

        Returns:
            str: G-code file name.
        """
        return str(self.__get("gcode_file", ""))

    def get_current_stage(self) -> int:
        """
        Get the current stage of the printer.

        Returns:
            int: Current printer stage.
        """
        return int(self.__get("stg_cur", 0))

    def get_print_type(self) -> str:
        """
        Get the current print type.

        Returns:
            str: Print type.
        """
        return str(self.__get("print_type", ""))

    def get_home_flag(self) -> int:
        """
        Get the home flag status.

        Returns:
            int: Home flag status.
        """
        return int(self.__get("home_flag", 0))

    def get_print_line_number(self) -> str:
        """
        Get the current print line number.

        Returns:
            str: Print line number.
        """
        return str(self.__get("mc_print_line_number", ""))

    def get_print_sub_stage(self) -> int:
        """
        Get the current print sub-stage.

        Returns:
            int: Print sub-stage.
        """
        return int(self.__get("mc_print_sub_stage", 0))

    def get_sdcard_status(self) -> bool:
        """
        Check if the SD card is present.

        Returns:
            bool: True if SD card is present, False otherwise.
        """
        return bool(self.__get("sdcard", False))

    def get_force_upgrade_status(self) -> bool:
        """
        Check if a force upgrade is required.

        Returns:
            bool: True if force upgrade is required, False otherwise.
        """
        return bool(self.__get("force_upgrade", False))

    def get_production_state(self) -> str:
        """
        Get the production state of the machine.

        Returns:
            str: Production state.
        """
        return str(self.__get("mess_production_state", ""))

    def get_current_layer_number(self) -> int:
        """
        Get the current layer number of the print.

        Returns:
            int: Current layer number.
        """
        return int(self.__get("layer_num", 0))

    def get_total_layer_number(self) -> int:
        """
        Get the total number of layers for the print.

        Returns:
            int: Total layer number.
        """
        return int(self.__get("total_layer_num", 0))

    def get_skipped_objects(self) -> list:
        """
        Get the list of skipped objects during printing.

        Returns:
            list: List of skipped objects.
        """
        return self.__get("s_obj", [])

    def get_filament_backup(self) -> list:
        """
        Get the filament backup information.

        Returns:
            list: Filament backup information.
        """
        return self.__get("filam_bak", [])

    def get_fan_gear_status(self) -> int:
        """
        Get the fan gear status.

        Returns:
            int: Fan gear status.
        """
        return int(self.__get("fan_gear", 0))

    def get_nozzle_diameter(self) -> float:
        """
        Get the nozzle diameter.

        Returns:
            float: Nozzle diameter in mm.
        """
        return float(self.__get("nozzle_diameter", 0.0))

    def get_nozzle_type(self) -> str:
        """
        Get the type of nozzle installed.

        Returns:
            str: Nozzle type.
        """
        return str(self.__get("nozzle_type", ""))

    def get_calibration_version(self) -> int:
        """
        Get the calibration version.

        Returns:
            int: Calibration version number.
        """
        return int(self.__get("cali_version", 0))