"""
Client module for connecting to the Bambulabs 3D printer API
and getting all the printer data.
"""

__all__ = ['Printer']

import inspect
import json
import base64
from io import BytesIO
from typing import Any, BinaryIO

from bambulabs_api.ams import AMSHub
from bambulabs_api.filament_info import FilamentTray
from bambulabs_api.states_info import PrintStatus
from .camera_client import PrinterCamera
from .ftp_client import PrinterFTPClient
from .mqtt_client import PrinterMQTTClient
from .filament_info import Filament, AMSFilamentSettings
from PIL import Image


class Printer:
    """
    Client Class for connecting to the Bambulabs 3D printer
    """

    def __init__(self, ip_address: str, access_code: str, serial: str,camera_thread:bool = True):
        self.ip_address = ip_address
        self.access_code = access_code
        self.serial = serial
        self.camera_thread = camera_thread
        self.mqtt_client = PrinterMQTTClient(self.ip_address,
                                             self.access_code,
                                             self.serial)
        if self.camera_thread:
            self.__printerCamera = PrinterCamera(self.ip_address,
                                             self.access_code)
        self.__printerFTPClient = PrinterFTPClient(self.ip_address,
                                                   self.access_code)


        self.method_dict = {name: getattr(self, name) for name, func in inspect.getmembers(self, predicate=inspect.ismethod) if not name.startswith('_') and name != 'method_dict'}


    def call_method_by_name(self, method_name, *args, **kwargs):
        """
        Dynamically call a method by its name from the method dictionary.

        Args:
            method_name (str): The name of the method to call.
            *args: Variable length argument list for the method.
            **kwargs: Arbitrary keyword arguments for the method.

        Returns:
            The result of the method call or None if the method doesn't exist.

        Raises:
            Exception: If the method call raises an exception, it's caught and printed.
        """
        if method_name in self.method_dict:
            try:
                result = self.method_dict[method_name](*args, **kwargs)
                print(f"Result of calling {method_name}: {result}")
                return result
            except Exception as e:
                print(f"An error occurred while calling {method_name}: {e}")
        else:
            print(f"Method {method_name} not found in the method dictionary.")
        return None


    def connect(self):
        """
        Connect to the printer
        """
        self.mqtt_client.connect()
        self.mqtt_client.start()
        if self.camera_thread:
            self.__printerCamera.start()

    def disconnect(self):
        """
        Disconnect from the printer
        """
        self.mqtt_client.stop()
        if self.camera_thread:
            self.__printerCamera.stop()

    def get_ready(self) -> bool:
        return self.mqtt_client.ready()


    def get_time(self) -> (int | str | None):
        """
        Get the remaining time of the print job in seconds.

        Returns
        -------
        int
            Remaining time of the print job in seconds.
        str
            "Unknown" if the remaining time is unknown.
        None if the printer is not printing.
        """
        return self.mqtt_client.get_remaining_time()

    def mqtt_dump(self) -> dict[Any, Any]:
        """
        Get the mqtt dump of the messages recorded from the printer

        Returns:
            dict[Any, Any]: the json that is recorded from the printer.
        """
        return self.mqtt_client.dump()

    def get_percentage(self) -> (int | str | None):
        """
        Get the percentage of the print job completed.

        Returns
        -------
        int
            Percentage of the print job completed.
        str
            "Unknown" if the percentage is unknown.
        None if the printer is not printing.
        """
        return self.mqtt_client.get_last_print_percentage()

    def get_state(self) -> str:
        """
        Get the state of the printer.

        Returns
        -------
        str
            The state of the printer.
        """
        return self.mqtt_client.get_printer_state().name

    def get_print_speed(self) -> int:
        """
        Get the print speed of the printer.

        Returns
        -------
        int
            The print speed of the printer.
        """
        return self.mqtt_client.get_print_speed()

    def get_bed_temperature(self) -> float | None:
        """
        Get the bed temperature of the printer.
        NOT IMPLEMENTED YET

        Returns
        -------
        float
            The bed temperature of the printer.
        None if the printer is not printing.
        """
        return self.mqtt_client.get_bed_temperature()

    def get_nozzle_diameter(self) -> float | None:
        """
        Get the nozzle diameter of the printer.
        
        Returns
        -------
        float
            The nozzle diameter of the printer.
        """
        return self.mqtt_client.get_nozzle_diameter()

    def get_nozzle_type(self) -> str | None:
        """
        Get the nozzle material of the printer.

        Returns
        -------
        str
            The nozzle material of the printer.
        """
        return self.mqtt_client.get_nozzle_type()



    def get_nozzle_temperature(self) -> float | None:
        """
        Get the nozzle temperature of the printer.
        NOT IMPLEMENTED YET

        Returns
        -------
        float
            The nozzle temperature of the printer.
        None if the printer is not printing.
        """
        return self.mqtt_client.get_nozzle_temperature()

    def get_file_name(self) -> str:
        """
        Get the name of the file being printed.

        Returns
        -------
        str
            The name of the file being printed.
        """
        return self.mqtt_client.get_file_name()

    def get_light_state(self) -> str:
        """
        Get the state of the printer light.

        Returns
        -------
        str
            The state of the printer light.
        """
        return self.mqtt_client.get_light_state()

    def turn_light_on(self) -> bool:
        """
        Turn on the printer light.

        Returns
        -------
        bool
            True if the light is turned on successfully.
        """
        return self.mqtt_client.turn_light_on()

    def turn_light_off(self) -> bool:
        """
        Turn off the printer light.

        Returns
        -------
        bool
            True if the light is turned off successfully.
        """
        return self.mqtt_client.turn_light_off()

    def gcode(self, gcode: str | list[str]) -> bool:
        """
        Send a gcode command to the printer.

        Parameters
        ----------
        gcode : str | list[str]
            The gcode command or list of gcode commands to be sent.

        Returns
        -------
        bool
            True if the gcode command is sent successfully.

        Raises
        ------
        ValueError
            If the gcode command is invalid.
        """
        return self.mqtt_client.send_gcode(gcode)

    def upload_file(self, file: BinaryIO, filename: str = "ftp_upload.gcode") -> str:  # noqa
        """
        Upload a file to the printer.

        Parameters
        ----------
        file : BinaryIO
            The file to be uploaded.
        filename : str, optional
            The name of the file, by default "ftp_upload.gcode".

        Returns
        -------
        str
            The path of the uploaded file.
        """
        try:
            if file and filename:
                return self.__printerFTPClient.upload_file(file, filename)
        except Exception as e:
            raise Exception(f"Exception occurred during file upload: {e}")  # noqa  # pylint: disable=raise-missing-from,broad-exception-raised
        finally:
            file.close()
        return "No file uploaded."

    def start_print_min(self, filename: str,
                    plate_number: int,
                    use_ams: bool = True,
                    ams_mapping: list[int] = [0],
                    skip_objects: list[int] | None = None,
                    ) -> bool:
        """
        Start printing a file.

        Parameters
        ----------
        filename : str
            The name of the file to be printed.
        plate_number : int
            The plate number of the file to be printed.
        use_ams : bool, optional
            Whether to use the AMS system, by default True.
        ams_mapping : list[int], optional
            The mapping of the filament trays to the plate numbers,
            by default [0].
        skip_objects (list[int] | None, optional): List of gcode objects to
            skip. Defaults to None.

        Returns
        -------
        bool
            True if the file is printed successfully.
        """
        return self.mqtt_client.start_print_3mf(filename,
                                                plate_number,
                                                use_ams,
                                                ams_mapping,
                                                skip_objects)

    def start_print(self,filename: str,
                        plate_number: int,
                        bed_leveling: bool = True,
                        flow_calibration: bool = False,
                        vibration_calibration: bool = False,
                        bed_type:str = "textured_plate",
                        use_ams: bool = True,
                        ams_mapping: list[int] = [0],
                        skip_objects: list[int] | None = None,
                        ) -> bool:
        return self.mqtt_client.start_print_3mf(filename=filename,
                                                plate_number=plate_number,
                                                bed_leveling=bed_leveling,
                                                flow_calibration=flow_calibration,
                                                vibration_calibration=vibration_calibration,
                                                bed_type=bed_type,
                                                use_ams=use_ams,
                                                ams_mapping=ams_mapping,
                                                skip_objects=skip_objects,)

    def stop_print(self) -> bool:
        """
        Stop the printer from printing.

        Returns
        -------
        bool
            True if the printer is stopped successfully.
        """
        return self.mqtt_client.stop_print()

    def pause_print(self) -> bool:
        """
        Pause the printer from printing.

        Returns
        -------
        bool
            True if the printer is paused successfully.
        """
        return self.mqtt_client.pause_print()

    def resume_print(self) -> bool:
        """
        Resume the printer from printing.

        Returns
        -------
        bool
            True if the printer is resumed successfully.
        """
        return self.mqtt_client.resume_print()

    def set_bed_temperature(self, temperature: int) -> bool:
        """
        Set the bed temperature of the printer.

        Parameters
        ----------
        temperature : int
            The temperature to be set.

        Returns
        -------
        bool
            True if the temperature is set successfully.
        """
        return self.mqtt_client.set_bed_temperature(temperature)

    def home_printer(self) -> bool:
        """
        Home the printer.

        Returns
        -------
        bool
            True if the printer is homed successfully.
        """
        return self.mqtt_client.auto_home()

    def move_z_axis(self, height: int) -> bool:
        """
        Move the Z-axis of the printer.

        Parameters
        ----------
        height : float
            The height for the bed.

        Returns
        -------
        bool
            True if the Z-axis is moved successfully.
        """
        return self.mqtt_client.set_bed_height(height)

    def set_filament_printer(
        self,
        color: str,
        filament: str | AMSFilamentSettings,
        ams_id: int = 255,
        tray_id: int = 254,
    ) -> bool:
        """
        Set the filament of the printer.

        Parameters
        ----------
        color : str
            The color of the filament.
        filament : str | AMSFilamentSettings
            The filament to be set.
        ams_id : int
            The index of the AMS, by default the external spool 255.
        tray_id : int
            The index of the spool/tray in the ams, by default the external
            spool 254.

        Returns
        -------
        bool
            True if the filament is set successfully.
        """
        assert len(color) == 6, "Color must be a 6 character hex code"
        if isinstance(filament, str) or isinstance(filament, AMSFilamentSettings):  # type: ignore # noqa: E501
            filament = Filament(filament)
        else:
            raise ValueError(
                "Filament must be a string or AMSFilamentSettings object")
        return self.mqtt_client.set_printer_filament(
            filament,
            color,
            ams_id=ams_id,
            tray_id=tray_id)

    def set_nozzle_temperature(self, temperature: int) -> bool:
        """
        Set the nozzle temperature of the printer.

        Parameters
        ----------
        temperature : int
            The temperature to be set.

        Returns
        -------
        bool
            True if the temperature is set successfully.
        """
        return self.mqtt_client.set_nozzle_temperature(temperature)

    def set_print_speed(self, speed_lvl: int) -> bool:
        """
        Set the print speed of the printer.

        Parameters
        ----------
        speed_lvl : int
            The speed level to be set.
            0: Slowest
            1: Slow
            2: Fast
            3: Fastest

        Returns
        -------
        bool
            True if the speed level is set successfully.
        """
        assert 0 <= speed_lvl <= 3, "Speed level must be between 0 and 3"
        return self.mqtt_client.set_print_speed_lvl(speed_lvl)

    def delete_file(self, file_path: str) -> str:
        """
        Delete a file from the printer.

        Parameters
        ----------
        file_path : str
            The path of the file to be deleted.

        Returns
        -------
        str
            The path of the deleted file.
        """
        return self.__printerFTPClient.delete_file(file_path)

    def calibrate_printer(self, bed_level: bool = True,
                          motor_noise_calibration: bool = True,
                          vibration_compensation: bool = True) -> bool:
        """
        Calibrate the printer.

        Parameters
        ----------
        bed_level : bool, optional
            Whether to calibrate the bed level, by default True.
        motor_noise_calibration : bool, optional
            Whether to calibrate the motor noise, by default True.
        vibration_compensation : bool, optional
            Whether to calibrate the vibration compensation, by default True.

        Returns
        -------
        bool
            True if the printer is calibrated successfully.
        """
        return self.mqtt_client.calibration(bed_level,
                                            motor_noise_calibration,
                                            vibration_compensation)

    def load_filament_spool(self) -> bool:
        """
        Load the filament spool to the printer.

        Returns
        -------
        bool
            True if the filament spool is loaded successfully.
        """
        return self.mqtt_client.load_filament_spool()

    def unload_filament_spool(self) -> bool:
        """
        Unload the filament spool from the printer.

        Returns
        -------
        bool
            True if the filament spool is unloaded successfully.
        """
        return self.mqtt_client.unload_filament_spool()

    def retry_filament_action(self) -> bool:
        """
        Retry the filament action.

        Returns
        -------
        bool
            True if the filament action is retried successfully.
        """
        return self.mqtt_client.resume_filament_action()

    def get_camera_frame(self) -> str:
        """
        Get the camera frame of the printer.

        Returns
        -------
        str
            Base64 encoded image of the camera frame.
        """
        return self.get_camera_frame_()

    def get_camera_frame_(self) -> str:
        return self.__printerCamera.get_frame()

    def get_camera_image(self) -> Image.Image:
        """
        Get the camera frame of the printer.

        Returns
        -------
        Image.Image
            Pillow Image of printer camera frame.
        """
        im = Image.open(BytesIO(base64.b64decode(self.get_camera_frame_())))
        return im

    def get_current_state(self) -> PrintStatus:
        """
        Get the current state of the printer.

        Returns
        -------
        PrintStatus
            The current state of the printer.
        """
        return self.mqtt_client.get_current_state()

    def get_skipped_objects(self) -> list[int]:
        """
        Get the current state of the printer.

        Returns
        -------
        PrintStatus
            The current state of the printer.
        """
        return self.mqtt_client.get_skipped_objects()

    def skip_objects(self, obj_list: list[int]) -> bool:
        """
        Skip Objects during printing.

        Args:
            obj_list (list[int]): object list to skip objects.

        Returns:
            bool: if publish command is successful
        """
        return self.mqtt_client.skip_objects(obj_list=obj_list)

    def set_part_fan_speed(self, speed: int | float) -> bool:
        """
        Set the fan speed of the part fan

        Args:
            speed (int | float): The speed to set the part fan

        Returns:
            bool: success of setting the fan speed
        """
        return self.mqtt_client.set_part_fan_speed(speed)

    def set_aux_fan_speed(self, speed: int | float) -> bool:
        """
        Set the fan speed of the aux part fan

        Args:
            speed (int | float): The speed to set the part fan

        Returns:
            bool: success of setting the fan speed
        """
        return self.mqtt_client.set_aux_fan_speed(speed)

    def set_chamber_fan_speed(self, speed: int | float) -> bool:
        """
        Set the fan speed of the chamber fan

        Args:
            speed (int | float): The speed to set the part fan

        Returns:
            bool: success of setting the fan speed
        """
        return self.mqtt_client.set_chamber_fan_speed(speed)

    def set_auto_step_recovery(self, auto_step_recovery: bool = True) -> bool:
        """
        Set whether or not to set auto step recovery

        Args:
            auto_step_recovery (bool): flag to set auto step recovery.
                Default True.

        Returns:
            bool: success of the auto step recovery command command
        """
        return self.mqtt_client.set_auto_step_recovery(
            auto_step_recovery)

    def vt_tray(self) -> FilamentTray:
        """
        Get the filament information from the tray information.

        Returns:
            Filament: filament information
        """
        return self.mqtt_client.vt_tray()

    def ams_hub(self) -> AMSHub:
        """
        Get ams hub, all AMS's hooked up to printer

        Returns:
            AMSHub: ams information
        """
        self.mqtt_client.process_ams()
        return self.mqtt_client.ams_hub

    def get_chamber_temperature(self) -> float:
        """
        Get the current chamber temperature.

        Returns:
            float: Chamber temperature in degrees Celsius.
        """
        return self.mqtt_client.get_chamber_temperature()

    def get_print_stage(self) -> str:
        """
        Get the current print stage.

        Returns:
            str: Current print stage.
        """
        return str(self.mqtt_client.get_current_state())

    def get_heatbreak_fan_speed(self) -> str:
        """
        Get the heatbreak fan speed.

        Returns:
            str: Heatbreak fan speed.
        """
        return self.mqtt_client.get_heatbreak_fan_speed()

    def get_cooling_fan_speed(self) -> str:
        """
        Get the cooling fan speed.

        Returns:
            str: Cooling fan speed.
        """
        return self.mqtt_client.get_cooling_fan_speed()

    def get_big_fan1_speed(self) -> str:
        """
        Get the speed of big fan 1.

        Returns:
            str: Speed of big fan 1.
        """
        return self.mqtt_client.get_big_fan1_speed()

    def get_big_fan2_speed(self) -> str:
        """
        Get the speed of big fan 2.

        Returns:
            str: Speed of big fan 2.
        """
        return self.mqtt_client.get_big_fan2_speed()

    def get_print_percentage(self) -> int:
        """
        Get the percentage of the print completed.

        Returns:
            int: Percentage of print completion.
        """
        return self.mqtt_client.get_last_print_percentage()

    def get_remaining_print_time(self) -> int:
        """
        Get the remaining time for the print in seconds.

        Returns:
            int: Remaining time for the print.
        """
        return self.mqtt_client.get_remaining_time()

    def get_ams_status(self) -> int:
        """
        Get the AMS status.

        Returns:
            int: AMS status code.
        """
        return self.mqtt_client.get_ams_status()

    def get_ams_rfid_status(self) -> int:
        """
        Get the AMS RFID status.

        Returns:
            int: AMS RFID status code.
        """
        return self.mqtt_client.get_ams_rfid_status()

    def get_hardware_switch_state(self) -> int:
        """
        Get the hardware switch state.

        Returns:
            int: Hardware switch state.
        """
        return self.mqtt_client.get_hardware_switch_state()

    def get_print_speed_level(self) -> int:
        """
        Get the print speed level.

        Returns:
            int: Print speed level.
        """
        return self.mqtt_client.get_print_speed_level()

    def get_print_error(self) -> int:
        """
        Get the print error status.

        Returns:
            int: Print error status.
        """
        return self.mqtt_client.get_print_error()

    def get_lifecycle(self) -> str:
        """
        Get the lifecycle status of the printer.

        Returns:
            str: Lifecycle status.
        """
        return self.mqtt_client.get_lifecycle()

    def get_wifi_signal(self) -> str:
        """
        Get the WiFi signal strength.

        Returns:
            str: WiFi signal strength.
        """
        return self.mqtt_client.get_wifi_signal()

    def get_gcode_state(self) -> str:
        """
        Get the current G-code state.

        Returns:
            str: G-code state.
        """
        return self.mqtt_client.get_gcode_state()

    def get_gcode_file_prepare_percentage(self) -> int:
        """
        Get the percentage of the G-code file preparation completed.

        Returns:
            int: G-code file preparation percentage.
        """
        return self.mqtt_client.get_gcode_file_prepare_percentage()

    def get_queue_number(self) -> int:
        """
        Get the current number in the print queue.

        Returns:
            int: Queue number.
        """
        return self.mqtt_client.get_queue_number()

    def get_queue_total(self) -> int:
        """
        Get the total number of items in the print queue.

        Returns:
            int: Total queue items.
        """
        return self.mqtt_client.get_queue_total()

    def get_queue_estimated_time(self) -> int:
        """
        Get the estimated time for the queue in seconds.

        Returns:
            int: Estimated queue time.
        """
        return self.mqtt_client.get_queue_estimated_time()

    def get_queue_status(self) -> int:
        """
        Get the status of the queue.

        Returns:
            int: Queue status.
        """
        return self.mqtt_client.get_queue_status()

    def get_project_id(self) -> str:
        """
        Get the current project ID.

        Returns:
            str: Project ID.
        """
        return self.mqtt_client.get_project_id()

    def get_profile_id(self) -> str:
        """
        Get the current profile ID.

        Returns:
            str: Profile ID.
        """
        return self.mqtt_client.get_profile_id()

    def get_task_id(self) -> str:
        """
        Get the current task ID.

        Returns:
            str: Task ID.
        """
        return self.mqtt_client.get_task_id()

    def get_subtask_id(self) -> str:
        """
        Get the current subtask ID.

        Returns:
            str: Subtask ID.
        """
        return self.mqtt_client.get_subtask_id()

    def get_subtask_name(self) -> str:
        """
        Get the name of the current subtask.

        Returns:
            str: Subtask name.
        """
        return self.mqtt_client.get_subtask_name()

    def get_gcode_file(self) -> str:
        """
        Get the name of the G-code file currently in use.

        Returns:
            str: G-code file name.
        """
        return self.mqtt_client.get_file_name()

    def get_current_stage(self) -> int:
        """
        Get the current stage of the printer.

        Returns:
            int: Current printer stage.
        """
        return self.mqtt_client.get_current_stage()



    def get_print_type(self) -> str:
        """
        Get the current print type.

        Returns:
            str: Print type.
        """
        return self.mqtt_client.get_print_type()

    def get_home_flag(self) -> int:
        """
        Get the home flag status.

        Returns:
            int: Home flag status.
        """
        return self.mqtt_client.get_home_flag()

    def get_print_line_number(self) -> str:
        """
        Get the current print line number.

        Returns:
            str: Print line number.
        """
        return self.mqtt_client.get_print_line_number()

    def get_print_sub_stage(self) -> int:
        """
        Get the current print sub-stage.

        Returns:
            int: Print sub-stage.
        """
        return self.mqtt_client.get_print_sub_stage()

    def get_sdcard_status(self) -> bool:
        """
        Check if the SD card is present.

        Returns:
            bool: True if SD card is present, False otherwise.
        """
        return self.mqtt_client.get_sdcard_status()

    def get_force_upgrade_status(self) -> bool:
        """
        Check if a force upgrade is required.

        Returns:
            bool: True if force upgrade is required, False otherwise.
        """
        return self.mqtt_client.get_force_upgrade_status()

    def get_production_state(self) -> str:
        """
        Get the production state of the machine.

        Returns:
            str: Production state.
        """
        return self.mqtt_client.get_production_state()

    def get_current_layer_number(self) -> int:
        """
        Get the current layer number of the print.

        Returns:
            int: Current layer number.
        """
        return self.mqtt_client.get_current_layer_number()

    def get_total_layer_number(self) -> int:
        """
        Get the total number of layers for the print.

        Returns:
            int: Total layer number.
        """
        return self.mqtt_client.get_total_layer_number()



    def get_filament_backup(self) -> list:
        """
        Get the filament backup information.

        Returns:
            list: Filament backup information.
        """
        return self.mqtt_client.get_filament_backup()

    def get_fan_gear_status(self) -> int:
        """
        Get the fan gear status.

        Returns:
            int: Fan gear status.
        """
        return self.mqtt_client.get_fan_gear_status()


    def get_calibration_version(self) -> int:
        """
        Get the calibration version.

        Returns:
            int: Calibration version number.
        """
        return self.mqtt_client.get_calibration_version()

    def to_json(self) -> str:
        """
        Convert the Printer instance to a JSON string.

        This method serializes the state and basic information of the Printer
        object into a JSON format. Note that complex objects like MQTTClient,
        PrinterCamera, or PrinterFTPClient are not serialized in detail; only
        their class names are included to prevent circular references and because
        their internal state might not be serializable or relevant for JSON representation.

        Returns:
            str: A JSON string representation of the Printer object.
        """

        # Start with basic attributes
        json_data = {
            "ip_address": self.ip_address,
            "access_code": self.access_code,
            "serial": self.serial,
            "state": {
                "ready": self.get_ready(),
                "time_remaining": self.get_time(),
                "percentage": self.get_percentage(),
                "printer_state": self.get_state(),
                "print_speed": self.get_print_speed(),
                "bed_temperature": self.get_bed_temperature(),
                "nozzle_diameter": self.get_nozzle_diameter(),
                "nozzle_type": self.get_nozzle_type(),
                "nozzle_temperature": self.get_nozzle_temperature(),
                "file_name": self.get_file_name(),
                "light_state": self.get_light_state(),
                "current_state": str(self.get_current_state()),
                "skipped_objects": self.get_skipped_objects(),
                "chamber_temperature": self.get_chamber_temperature(),
                "print_stage": self.get_print_stage(),
                "heatbreak_fan_speed": self.get_heatbreak_fan_speed(),
                "cooling_fan_speed": self.get_cooling_fan_speed(),
                "big_fan1_speed": self.get_big_fan1_speed(),
                "big_fan2_speed": self.get_big_fan2_speed(),
                "remaining_print_time": self.get_remaining_print_time(),
                "ams_status": self.get_ams_status(),
                "ams_rfid_status": self.get_ams_rfid_status(),
                "hardware_switch_state": self.get_hardware_switch_state(),
                "print_speed_level": self.get_print_speed_level(),
                "print_error": self.get_print_error(),
                "lifecycle": self.get_lifecycle(),
                "wifi_signal": self.get_wifi_signal(),
                "gcode_state": self.get_gcode_state(),
                "gcode_file_prepare_percentage": self.get_gcode_file_prepare_percentage(),
                "queue_number": self.get_queue_number(),
                "queue_total": self.get_queue_total(),
                "queue_estimated_time": self.get_queue_estimated_time(),
                "queue_status": self.get_queue_status(),
                "project_id": self.get_project_id(),
                "profile_id": self.get_profile_id(),
                "task_id": self.get_task_id(),
                "subtask_id": self.get_subtask_id(),
                "subtask_name": self.get_subtask_name(),
                "gcode_file": self.get_gcode_file(),
                "current_stage": self.get_current_stage(),
                "print_type": self.get_print_type(),
                "home_flag": self.get_home_flag(),
                "print_line_number": self.get_print_line_number(),
                "print_sub_stage": self.get_print_sub_stage(),
                "sdcard_status": self.get_sdcard_status(),
                "force_upgrade_status": self.get_force_upgrade_status(),
                "production_state": self.get_production_state(),
                "current_layer_number": self.get_current_layer_number(),
                "total_layer_number": self.get_total_layer_number(),
                "filament_backup": self.get_filament_backup(),
                "fan_gear_status": self.get_fan_gear_status(),
                "calibration_version": self.get_calibration_version()
            }
        }

        # Convert to JSON string
        return json.dumps(json_data, default=lambda o: o.__dict__ if hasattr(o, '__dict__') else str(o), sort_keys=True,
                          indent=4)