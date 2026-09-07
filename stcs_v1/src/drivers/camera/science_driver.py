# src/drivers/camera/science_driver.py
import sys
import os
import logging
import time
import glob
import platform

logger = logging.getLogger("ScienceDriver")

class ScienceCameraDriver:
    """
    Driver for Princeton Instruments CCD via LightField Automation.
    Expanded: Readout Modes, Metrics, File Saving, Hardware I/O Triggers, and Time Stamping.
    Includes comprehensive validation (.Exists checks) and stabilization to prevent COM crashes.
    """
    def __init__(self):
        self.automation = None
        self.experiment = None
        self.mock_mode = False
        
        # Default save directory
        self.save_dir = os.path.abspath(os.path.join(os.getcwd(), "data", "captures"))
        os.makedirs(self.save_dir, exist_ok=True)
        
        # 1. Architecture Check
        bitness = platform.architecture()[0]
        if "64" not in bitness:
            logger.critical(f"ARCHITECTURE ERROR: Running {bitness} Python. LightField requires 64-bit!")
            self.mock_mode = True
            return

        # 2. Path Check
        self.lf_root = os.environ.get('LIGHTFIELD_ROOT', r"C:\Program Files\Princeton Instruments\LightField")
        if not os.path.exists(self.lf_root):
            logger.warning("LightField root not found. MOCK mode.")
            self.mock_mode = True
            return

        # 3. Load DLLs
        try:
            import clr
            sys.path.append(self.lf_root)
            sys.path.append(os.path.join(self.lf_root, "AddInViews"))
            
            clr.AddReference('PrincetonInstruments.LightField.AutomationV5')
            clr.AddReference('PrincetonInstruments.LightFieldAddInSupportServices')
            try: clr.AddReference('PrincetonInstruments.LightFieldViewV5')
            except: pass

            from PrincetonInstruments.LightField.Automation import Automation
            from PrincetonInstruments.LightField.AddIns import CameraSettings, ExperimentSettings, RegionOfInterest, DeviceType
            from System.Collections.Generic import List
            from System import String, Int32, Int64, Double, Array 
            
            self.LF_Automation = Automation
            self.LF_ListString = List[String]
            self.LF_CameraSettings = CameraSettings
            self.LF_ExperimentSettings = ExperimentSettings
            self.LF_RegionOfInterest = RegionOfInterest 
            self.LF_DeviceType = DeviceType
            
            self.String = String
            self.Int32 = Int32
            self.Int64 = Int64
            self.Double = Double
            self.Array = Array
            
            logger.info("LightField Assemblies Loaded.")
            
        except ImportError:
            logger.critical("pythonnet not installed. MOCK mode.")
            self.mock_mode = True
        except Exception as e:
            logger.critical(f"CLR Load Error: {e}")
            self.mock_mode = True

    def connect(self):
        """
        Connects to LightField, ensures a camera is loaded, and prepares for interaction.
        """
        if self.mock_mode: return True
        try:
            if self.automation:
                try: 
                    _ = self.experiment.IsRunning
                    return True
                except: 
                    self.automation = None

            args = self.LF_ListString()
            self.automation = self.LF_Automation(True, args)
            self.experiment = self.automation.LightFieldApplication.Experiment
            
            # --- DEVICE AUTO-LOADING ---
            # If no device is currently in the experiment, find available cameras and add the first one.
            if self.experiment.ExperimentDevices.Count == 0:
                logger.info("No devices in experiment. Searching for available cameras...")
                found_cam = False
                for device in self.automation.LightFieldApplication.Experiment.AvailableDevices:
                    if device.Type == self.LF_DeviceType.Camera:
                        self.experiment.Add(device)
                        logger.info(f"Automatically added Camera: {device.Model}")
                        found_cam = True
                        break
                
                if not found_cam:
                    logger.warning("No available cameras found in LightField!")
            
            # CRITICAL STABILIZATION: Wait for the experiment to be 'composed'.
            # Prevents 'Uninitialized object' errors during initial settings push.
            time.sleep(4.0) 
            
            logger.info("Connected to LightField. Normalizing initial state...")
            
            # Initial directory sync
            self.set_save_directory(self.save_dir)
            
            # Default to Full Frame (1)
            self.set_readout_mode("Full Frame")
            
            return True
        except Exception as e:
            logger.error(f"Connection Failed: {e}")
            self.automation = None
            return False

    def is_connected(self):
        """
        Dynamic check to see if the IPC connection to LightField is still alive.
        """
        if self.mock_mode: return True
        if not self.automation or not self.experiment: return False
        
        try:
            # Heartbeat check: Accessing a simple property to verify IPC pipe is intact
            _ = self.experiment.IsRunning
            return True
        except Exception as e:
            # If the pipe is broken or IPC failed, clean up and return false
            logger.error(f"LightField IPC connection lost: {e}")
            self._handle_crash()
            return False

    def _handle_crash(self):
        """Internal helper to reset driver state after a crash."""
        self.automation = None
        self.experiment = None

    # =========================================================================
    #  CORE ACQUISITION SETTINGS
    # =========================================================================

    def set_exposure(self, s):
        if self.mock_mode or not self.experiment: return
        try: 
            if self.experiment.Exists(self.LF_CameraSettings.ShutterTimingExposureTime):
                self.experiment.SetValue(self.LF_CameraSettings.ShutterTimingExposureTime, self.Double(s * 1000))
        except: self.is_connected()

    def set_shutter_mode(self, m):
        if self.mock_mode: return
        mp = {"normal": 1, "alwaysclosed": 2, "alwaysopen": 3, "openbeforetrigger": 4}
        k = str(m).replace(" ", "").lower()
        if k in mp and self.experiment:
            try: 
                if self.experiment.Exists(self.LF_CameraSettings.ShutterTimingMode):
                    self.experiment.SetValue(self.LF_CameraSettings.ShutterTimingMode, self.Int32(mp[k]))
            except: self.is_connected()

    def set_gain(self, g):
        if self.mock_mode: return
        mp = {"low": 1, "medium": 2, "high": 3}
        if g.lower() in mp and self.experiment:
            try: 
                if self.experiment.Exists(self.LF_CameraSettings.AdcAnalogGain):
                    self.experiment.SetValue(self.LF_CameraSettings.AdcAnalogGain, self.Int32(mp[g.lower()]))
            except: self.is_connected()

    def set_adc_speed(self, s):
        if self.mock_mode: return
        mp = {"2 MHz": 2.0, "100 kHz": 0.1}
        if s in mp and self.experiment:
            try: 
                if self.experiment.Exists(self.LF_CameraSettings.AdcSpeed):
                    self.experiment.SetValue(self.LF_CameraSettings.AdcSpeed, self.Double(mp[s]))
            except: self.is_connected()

    def set_temperature(self, t):
        if self.mock_mode or not self.experiment: return
        try: 
            if self.experiment.Exists(self.LF_CameraSettings.SensorTemperatureSetPoint):
                self.experiment.SetValue(self.LF_CameraSettings.SensorTemperatureSetPoint, self.Double(t))
        except: self.is_connected()

    def set_readout_mode(self, mode_str):
        if self.mock_mode: return
        mode_map = {"full frame": 1, "kinetics": 3}
        key = str(mode_str).lower()
        if key in mode_map:
            try:
                if self.experiment and self.experiment.Exists(self.LF_CameraSettings.ReadoutControlMode):
                    self.experiment.SetValue(self.LF_CameraSettings.ReadoutControlMode, self.Int32(mode_map[key]))
            except: self.is_connected()

    # =========================================================================
    #  NEW FEATURES (Frames, TimeStamp, Tracking)
    # =========================================================================

    def set_frames_to_save(self, frames):
        if self.mock_mode or not self.experiment: return
        try:
            if self.experiment.Exists(self.LF_ExperimentSettings.AcquisitionFramesToStore):
                self.experiment.SetValue(self.LF_ExperimentSettings.AcquisitionFramesToStore, self.Int64(frames))
        except: self.is_connected()

    def set_time_stamping(self, mask):
        if self.mock_mode or not self.experiment: return
        try:
            if self.experiment.Exists(self.LF_CameraSettings.AcquisitionTimeStampingStamps):
                self.experiment.SetValue(self.LF_CameraSettings.AcquisitionTimeStampingStamps, self.Int32(mask))
        except: self.is_connected()

    def set_frame_tracking(self, enabled):
        if self.mock_mode or not self.experiment: return
        try:
            if self.experiment.Exists(self.LF_CameraSettings.AcquisitionFrameTrackingEnabled):
                self.experiment.SetValue(self.LF_CameraSettings.AcquisitionFrameTrackingEnabled, enabled)
        except: self.is_connected()

    # =========================================================================
    #  TRIGGERS
    # =========================================================================

    def set_trigger_response(self, mode_str):
        if self.mock_mode: return
        mp = {"no response": 1, "readout per trigger": 2, "shift per trigger": 3}
        k = str(mode_str).lower()
        if k in mp and self.experiment:
            try:
                if self.experiment.Exists(self.LF_CameraSettings.HardwareIOTriggerResponse):
                    self.experiment.SetValue(self.LF_CameraSettings.HardwareIOTriggerResponse, self.Int32(mp[k]))
            except: self.is_connected()

    def set_trigger_determination(self, det_str):
        if self.mock_mode: return
        mp = {"negative polarity": 2, "positive polarity": 1}
        k = str(det_str).lower()
        if k in mp and self.experiment:
            try:
                if self.experiment.Exists(self.LF_CameraSettings.HardwareIOTriggerDetermination):
                    self.experiment.SetValue(self.LF_CameraSettings.HardwareIOTriggerDetermination, self.Int32(mp[k]))
            except: self.is_connected()

    def set_output_signal(self, sig_str):
        if self.mock_mode: return
        mp = {"not reading out": 1, "shutter open": 2, "busy": 3, "always low": 4, "always high": 5, "acquiring": 6}
        k = str(sig_str).lower()
        if k in mp and self.experiment:
            try:
                if self.experiment.Exists(self.LF_CameraSettings.HardwareIOOutputSignal):
                    self.experiment.SetValue(self.LF_CameraSettings.HardwareIOOutputSignal, self.Int32(mp[k]))
            except: self.is_connected()

    # =========================================================================
    #  ROI & BINNING (RESTORED MISSING LOGIC)
    # =========================================================================

    def set_roi_selection(self, s):
        if self.mock_mode: return
        mp = {"fullsensor":1,"binnedsensor":2,"linesensor":3,"customregions":4}
        k = str(s).replace(" ","").lower()
        if k in mp and self.experiment:
            try: 
                if self.experiment.Exists(self.LF_CameraSettings.ReadoutControlRegionsOfInterestSelection):
                    self.experiment.SetValue(self.LF_CameraSettings.ReadoutControlRegionsOfInterestSelection, self.Int32(mp[k]))
            except: self.is_connected()

    def set_binned_params(self, x, y):
        if self.mock_mode or not self.experiment: return
        try:
            if self.experiment.Exists(self.LF_CameraSettings.ReadoutControlRegionsOfInterestBinnedSensorXBinning):
                self.experiment.SetValue(self.LF_CameraSettings.ReadoutControlRegionsOfInterestBinnedSensorXBinning, self.Int32(x))
            if self.experiment.Exists(self.LF_CameraSettings.ReadoutControlRegionsOfInterestBinnedSensorYBinning):
                self.experiment.SetValue(self.LF_CameraSettings.ReadoutControlRegionsOfInterestBinnedSensorYBinning, self.Int32(y))
        except: self.is_connected()

    def set_line_params(self, r):
        if self.mock_mode or not self.experiment: return
        try:
            if self.experiment.Exists(self.LF_CameraSettings.ReadoutControlRegionsOfInterestLineSensorRowBinning):
                self.experiment.SetValue(self.LF_CameraSettings.ReadoutControlRegionsOfInterestLineSensorRowBinning, self.Int32(r))
        except: self.is_connected()

    def set_custom_region(self, x, y, w, h, bx, by):
        if self.mock_mode: return
        try:
            if self.experiment and self.experiment.Exists(self.LF_CameraSettings.ReadoutControlRegionsOfInterestCustomRegions):
                roi = self.LF_RegionOfInterest(self.Int32(x), self.Int32(y), self.Int32(w), self.Int32(h), self.Int32(bx), self.Int32(by))
                arr = self.Array[self.LF_RegionOfInterest]([roi])
                self.experiment.SetValue(self.LF_CameraSettings.ReadoutControlRegionsOfInterestCustomRegions, arr)
        except: self.is_connected()

    def set_binning_provider(self, p):
        if self.mock_mode: return
        mp = {"hardware":1,"software":2}
        k = str(p).lower()
        if k in mp and self.experiment:
            try:
                if self.experiment.Exists(self.LF_CameraSettings.ReadoutControlRegionsOfInterestBinningProvider):
                    self.experiment.SetValue(self.LF_CameraSettings.ReadoutControlRegionsOfInterestBinningProvider, self.Int32(mp[k]))
            except: self.is_connected()

    # =========================================================================
    #  KINETICS CONTROL
    # =========================================================================

    def set_kinetics_window_height(self, height):
        if self.mock_mode: return
        try:
            if self.experiment.Exists(self.LF_CameraSettings.ReadoutControlKineticsWindowHeight):
                self.experiment.SetValue(self.LF_CameraSettings.ReadoutControlKineticsWindowHeight, self.Int32(height))
        except: self.is_connected()

    def set_storage_shift_rate(self, rate_us):
        if self.mock_mode: return
        try:
            if self.experiment.Exists(self.LF_CameraSettings.ReadoutControlStorageShiftRate):
                self.experiment.SetValue(self.LF_CameraSettings.ReadoutControlStorageShiftRate, self.Double(rate_us))
        except: self.is_connected()

    # =========================================================================
    #  FILE SAVE SETTINGS (RESTORED MISSING LOGIC)
    # =========================================================================

    def set_base_filename(self, n):
        if self.mock_mode or not self.experiment: return
        try:
            if self.experiment.Exists(self.LF_ExperimentSettings.FileNameGenerationBaseFileName):
                self.experiment.SetValue(self.LF_ExperimentSettings.FileNameGenerationBaseFileName, self.String(n))
        except: self.is_connected()
    
    def set_save_directory(self, p):
        if self.mock_mode or not self.experiment: return
        try:
            normalized_path = p.replace("/", "\\")
            if self.experiment.Exists(self.LF_ExperimentSettings.FileNameGenerationDirectory):
                self.experiment.SetValue(self.LF_ExperimentSettings.FileNameGenerationDirectory, self.String(normalized_path))
                logger.info(f"Set Save Directory to: {normalized_path}")
        except: self.is_connected()

    def set_attach_date(self, e):
        if self.mock_mode or not self.experiment: return
        try:
            if self.experiment.Exists(self.LF_ExperimentSettings.FileNameGenerationAttachDate):
                self.experiment.SetValue(self.LF_ExperimentSettings.FileNameGenerationAttachDate, e)
        except: self.is_connected()

    def set_attach_time(self, e):
        if self.mock_mode or not self.experiment: return
        try:
            if self.experiment.Exists(self.LF_ExperimentSettings.FileNameGenerationAttachTime):
                self.experiment.SetValue(self.LF_ExperimentSettings.FileNameGenerationAttachTime, e)
        except: self.is_connected()

    def set_attach_increment(self, e):
        if self.mock_mode or not self.experiment: return
        try:
            if self.experiment.Exists(self.LF_ExperimentSettings.FileNameGenerationAttachIncrement):
                self.experiment.SetValue(self.LF_ExperimentSettings.FileNameGenerationAttachIncrement, e)
        except: self.is_connected()

    def set_increment_number(self, v):
        if self.mock_mode or not self.experiment: return
        try:
            if self.experiment.Exists(self.LF_ExperimentSettings.FileNameGenerationIncrementNumber):
                self.experiment.SetValue(self.LF_ExperimentSettings.FileNameGenerationIncrementNumber, self.Int32(v))
        except: self.is_connected()

    def set_increment_digits(self, v):
        if self.mock_mode or not self.experiment: return
        try:
            if self.experiment.Exists(self.LF_ExperimentSettings.FileNameGenerationIncrementMinimumDigits):
                self.experiment.SetValue(self.LF_ExperimentSettings.FileNameGenerationIncrementMinimumDigits, self.Int32(v))
        except: self.is_connected()

    def set_date_format(self, f):
        if self.mock_mode or not self.experiment: return
        mp = {"yyyy-mm-dd":1, "yyyy-month-dd":2, "dd-mm-yyyy":3, "dd-month-yyyy":4, "mm-dd-yyyy":5, "month-dd-yyyy":6}
        k = str(f).lower().replace("_","-")
        if k in mp and self.experiment:
            try:
                if self.experiment.Exists(self.LF_ExperimentSettings.FileNameGenerationDateFormat):
                    self.experiment.SetValue(self.LF_ExperimentSettings.FileNameGenerationDateFormat, self.Int32(mp[k]))
            except: self.is_connected()

    def set_time_format(self, f):
        t = 2 if "ampm" in str(f).lower().replace("/","") else 1
        if self.experiment:
            try:
                if self.experiment.Exists(self.LF_ExperimentSettings.FileNameGenerationTimeFormat):
                    self.experiment.SetValue(self.LF_ExperimentSettings.FileNameGenerationTimeFormat, self.Int32(t))
            except: self.is_connected()

    # =========================================================================
    #  ACQUISITION LOOP & HELPERS
    # =========================================================================

    def get_example_filename(self):
        """Safely fetches the example filename."""
        if self.mock_mode: return "Mock.spe"
        try:
            if self.is_connected() and self.experiment:
                prop = self.LF_ExperimentSettings.FileNameGenerationExampleFileName
                if self.experiment.Exists(prop):
                    return self.experiment.GetValue(prop)
        except: pass
        return "N/A"

    def acquire_image(self):
        """
        Triggers acquisition and waits for completion with improved stabilization.
        """
        if self.mock_mode: 
            time.sleep(1); return os.path.join(self.save_dir, "mock.png")
        if not self.is_connected(): raise Exception("Disconnected")
        
        try:
            if not self.experiment or not hasattr(self.experiment, 'Acquire'):
                raise Exception("Experiment object not ready")

            logger.info("Triggering acquisition...")
            self.experiment.Acquire()
            
            # Wait for start
            time.sleep(1.0) 
            
            # Wait for finish
            for _ in range(120):
                if not self.is_connected(): raise Exception("LightField IPC Connection Lost.")
                if not self.experiment.IsRunning:
                    logger.info("Acquisition complete.")
                    break
                time.sleep(1.0)
            
            # CRITICAL STABILIZATION: Prevent COM Uninitialized errors
            time.sleep(3.0)
            
            files = glob.glob(os.path.join(self.save_dir, '*.spe'))
            if not files: return None
            return max(files, key=os.path.getctime)
            
        except Exception as e:
            logger.error(f"Acquire Error: {e}")
            self.is_connected()
            raise e

    def get_readout_status(self):
        status = {"time_ms": 0.0, "fps": 0.0, "frames_per": 0}
        if self.mock_mode: return {"time_ms": 150.0, "fps": 0.0, "frames_per": 0}
        try:
            if self.is_connected() and self.experiment:
                if self.experiment.Exists(self.LF_CameraSettings.ReadoutControlTime):
                    status["time_ms"] = self.experiment.GetValue(self.LF_CameraSettings.ReadoutControlTime)
                if self.experiment.Exists(self.LF_CameraSettings.AcquisitionFrameRate):
                    status["fps"] = self.experiment.GetValue(self.LF_CameraSettings.AcquisitionFrameRate)
                if self.experiment.Exists(self.LF_CameraSettings.AcquisitionFramesPerReadout):
                    status["frames_per"] = self.experiment.GetValue(self.LF_CameraSettings.AcquisitionFramesPerReadout)
        except: pass
        return status

    def get_current_temperature(self):
        if self.mock_mode: return -70.0
        try:
            if self.is_connected() and self.experiment: 
                if self.experiment.Exists(self.LF_CameraSettings.SensorTemperatureReading):
                    return self.experiment.GetValue(self.LF_CameraSettings.SensorTemperatureReading)
        except: pass
        return 0.0

    def dispose(self):
        if self.automation:
            try: self.automation.Dispose()
            except: pass
            self.automation = None