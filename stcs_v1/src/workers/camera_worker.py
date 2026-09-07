# src/workers/camera_worker.py
import logging
import queue
from PyQt6.QtCore import QThread, pyqtSignal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CameraWorker")

class CameraWorker(QThread):
    # Signals
    connection_status = pyqtSignal(bool, str)
    image_ready = pyqtSignal(str) 
    status_message = pyqtSignal(str)
    temperature_updated = pyqtSignal(float)
    example_filename_updated = pyqtSignal(str)
    readout_status_updated = pyqtSignal(dict) # Carries Time, FPS, Frames

    def __init__(self, driver):
        super().__init__()
        self.driver = driver
        self.running = False
        self.task_queue = queue.Queue()
        
    def run(self):
        self.running = True
        logger.info("Camera Worker Thread Started")
        
        while self.running:
            try:
                task = self.task_queue.get(timeout=0.1)
                cmd = task[0]
                data = task[1] if len(task) > 1 else None
                
                # --- CONNECTION ---
                if cmd == "CONNECT": self._do_connect()
                
                # --- ACQUISITION ---
                elif cmd == "ACQUIRE": self._do_acquire(data)
                elif cmd == "SET_TEMP": self._do_set_temp(data)
                elif cmd == "SET_GAIN": self._do_set_gain(data)
                elif cmd == "SET_SHUTTER": self._do_set_shutter(data)
                elif cmd == "SET_SPEED": self._do_set_speed(data)
                elif cmd == "SET_EXP": self._do_set_exposure(data)
                elif cmd == "SET_FRAMES": self._do_set_frames_to_save(data)
                elif cmd == "SET_STAMPS": self._do_set_time_stamping(data)
                elif cmd == "SET_TRACKING": self._do_set_frame_tracking(data)
                
                # --- TRIGGER ---
                elif cmd == "SET_TRIG_RESP": self._do_set_trigger_response(data)
                elif cmd == "SET_TRIG_DET": self._do_set_trigger_determination(data)
                elif cmd == "SET_TRIG_OUT": self._do_set_output_signal(data)
                
                # --- ROI ---
                elif cmd == "SET_ROI": self._do_set_roi(data)
                elif cmd == "SET_BIN": self._do_set_bin_params(data) 
                elif cmd == "SET_LINE": self._do_set_line_params(data)
                elif cmd == "SET_CUST": self._do_set_custom_roi(data) 
                elif cmd == "SET_PROV": self._do_set_provider(data)
                
                # --- READOUT ---
                elif cmd == "SET_R_MODE": self._do_set_readout_mode(data)
                elif cmd == "SET_K_H": self._do_set_kinetics_height(data)
                elif cmd == "SET_SHIFT": self._do_set_shift_rate(data)
                elif cmd == "GET_R_STAT": self._update_readout()
                
                # --- FILE SAVE ---
                elif cmd == "SET_FILE": self._do_set_filename(data)
                elif cmd == "SET_DIR": self._do_set_directory(data)
                elif cmd == "SET_DATE": self._do_set_attach_date(data)
                elif cmd == "SET_TIME": self._do_set_attach_time(data)
                elif cmd == "SET_INC": self._do_set_attach_increment(data)
                elif cmd == "SET_INC_N": self._do_set_inc_num(data)
                elif cmd == "SET_INC_D": self._do_set_inc_digits(data)
                elif cmd == "SET_DATE_F": self._do_set_date_fmt(data)
                elif cmd == "SET_TIME_F": self._do_set_time_fmt(data)
                elif cmd == "GET_EXAMPLE_NAME": self._do_get_example_name()
                
                # --- STATUS ---
                elif cmd == "POLL_TEMP": self._do_poll_temp()
                    
                self.task_queue.task_done()
            except queue.Empty: pass
            except Exception as e: 
                logger.error(f"Worker Loop Error: {e}")
                self._handle_possible_crash()

    def _handle_possible_crash(self):
        if not self.driver.is_connected():
            self.status_message.emit("CRITICAL: LightField connection lost!")
            self.connection_status.emit(False, "CRASH: Pipe Ended")

    def _do_connect(self):
        self.status_message.emit("Connecting to Camera...")
        success = self.driver.connect()
        msg = "Camera Connected" if success else "Camera Connection Failed"
        self.connection_status.emit(success, msg)
        if success:
            self._update_fname()
            self._update_readout()

    def _do_acquire(self, settings):
        self.status_message.emit(f"Exposing...")
        try:
            if 'exposure' in settings:
                self.driver.set_exposure(settings['exposure'])
            image_path = self.driver.acquire_image()
            if image_path:
                self.status_message.emit("Image Saved.")
                self.image_ready.emit(image_path)
                self._update_fname() 
            else:
                self.status_message.emit("Acquisition Failed: No Image File")
        except Exception as e:
            self.status_message.emit(f"Error: {str(e)}")
            self._handle_possible_crash()

    def _set(self, func, arg):
        try: func(arg)
        except Exception as e:
            logger.error(f"Set Error: {e}")
            self._handle_possible_crash()

    def _do_set_temp(self, d): self._set(self.driver.set_temperature, d)
    def _do_set_gain(self, d): self._set(self.driver.set_gain, d)
    def _do_set_shutter(self, d): self._set(self.driver.set_shutter_mode, d)
    def _do_set_speed(self, d): self._set(self.driver.set_adc_speed, d)
    def _do_set_exposure(self, d): self._set(self.driver.set_exposure, d)
    def _do_set_frames_to_save(self, d): self._set(self.driver.set_frames_to_save, d)
    def _do_set_time_stamping(self, d): self._set(self.driver.set_time_stamping, d)
    def _do_set_frame_tracking(self, d): self._set(self.driver.set_frame_tracking, d)
    
    def _do_set_trigger_response(self, d): self._set(self.driver.set_trigger_response, d)
    def _do_set_trigger_determination(self, d): self._set(self.driver.set_trigger_determination, d)
    def _do_set_output_signal(self, d): self._set(self.driver.set_output_signal, d)

    def _do_set_roi(self, d): self._set(self.driver.set_roi_selection, d)
    def _do_set_bin_params(self, d): self._set(lambda x: self.driver.set_binned_params(x[0], x[1]), d)
    def _do_set_line_params(self, d): self._set(self.driver.set_line_params, d)
    def _do_set_custom_roi(self, d): self._set(lambda x: self.driver.set_custom_region(x[0], x[1], x[2], x[3], x[4], x[5]), d)
    def _do_set_provider(self, d): self._set(self.driver.set_binning_provider, d)

    def _do_set_readout_mode(self, d): 
        self._set(self.driver.set_readout_mode, d)
        self._update_readout()
        
    def _do_set_kinetics_height(self, d): 
        self._set(self.driver.set_kinetics_window_height, d)
        self._update_readout()
        
    def _do_set_shift_rate(self, d): 
        self._set(self.driver.set_storage_shift_rate, d)
        self._update_readout()

    def _do_set_filename(self, d): self._set(self.driver.set_base_filename, d); self._update_fname()
    def _do_set_directory(self, d): self._set(self.driver.set_save_directory, d)
    def _do_set_attach_date(self, d): self._set(self.driver.set_attach_date, d); self._update_fname()
    def _do_set_attach_time(self, d): self._set(self.driver.set_attach_time, d); self._update_fname()
    def _do_set_attach_increment(self, d): self._set(self.driver.set_attach_increment, d); self._update_fname()
    def _do_set_inc_num(self, d): self._set(self.driver.set_increment_number, d); self._update_fname()
    def _do_set_inc_digits(self, d): self._set(self.driver.set_increment_digits, d); self._update_fname()
    def _do_set_date_fmt(self, d): self._set(self.driver.set_date_format, d); self._update_fname()
    def _do_set_time_fmt(self, d): self._set(self.driver.set_time_format, d); self._update_fname()

    def _do_get_example_name(self):
        self._update_fname()

    def _update_fname(self):
        if self.driver.is_connected():
            name = self.driver.get_example_filename()
            self.example_filename_updated.emit(name)
        else:
            self._handle_possible_crash()

    def _update_readout(self):
        if self.driver.is_connected():
            status = self.driver.get_readout_status()
            self.readout_status_updated.emit(status)
        else:
            self._handle_possible_crash()

    def _do_poll_temp(self):
        try:
            if not self.driver.is_connected(): 
                self.connection_status.emit(False, "Connection Lost")
                return
            t = self.driver.get_current_temperature()
            self.temperature_updated.emit(t)
        except Exception as e:
            logger.error(f"Polling failed: {e}")
            self._handle_possible_crash()

    # --- PUBLIC QUEUE METHODS ---
    def queue_connect(self): self.task_queue.put(("CONNECT",))
    def queue_acquire(self, settings): self.task_queue.put(("ACQUIRE", settings))
    def queue_set_temp(self, temp): self.task_queue.put(("SET_TEMP", temp))
    def queue_set_gain(self, gain): self.task_queue.put(("SET_GAIN", gain))
    def queue_set_shutter(self, mode): self.task_queue.put(("SET_SHUTTER", mode))
    def queue_set_speed(self, speed): self.task_queue.put(("SET_SPEED", speed))
    def queue_set_exposure(self, exp_time): self.task_queue.put(("SET_EXP", exp_time))
    def queue_set_frames_to_save(self, frames): self.task_queue.put(("SET_FRAMES", frames))
    def queue_set_time_stamps(self, mask): self.task_queue.put(("SET_STAMPS", mask))
    def queue_set_frame_tracking(self, enabled): self.task_queue.put(("SET_TRACKING", enabled))
    
    def queue_set_trigger_response(self, r): self.task_queue.put(("SET_TRIG_RESP", r))
    def queue_set_trigger_determination(self, d): self.task_queue.put(("SET_TRIG_DET", d))
    def queue_set_output_signal(self, s): self.task_queue.put(("SET_TRIG_OUT", s))
    
    # ROI
    def queue_set_roi(self, selection): self.task_queue.put(("SET_ROI", selection))
    def queue_set_bin_params(self, params): self.task_queue.put(("SET_BIN", params))
    def queue_set_line_params(self, rows): self.task_queue.put(("SET_LINE", rows))
    def queue_set_custom_roi(self, params): self.task_queue.put(("SET_CUST", params))
    def queue_set_provider(self, prov): self.task_queue.put(("SET_PROV", prov))
    
    # Readout
    def queue_set_readout_mode(self, mode): self.task_queue.put(("SET_R_MODE", mode))
    def queue_set_kinetics_height(self, h): self.task_queue.put(("SET_K_H", h))
    def queue_set_shift_rate(self, r): self.task_queue.put(("SET_SHIFT", r))
    def queue_get_readout_status(self): self.task_queue.put(("GET_R_STAT",))
    
    # File Save
    def queue_set_filename(self, name): self.task_queue.put(("SET_FILE", name))
    def queue_set_directory(self, path): self.task_queue.put(("SET_DIR", path))
    def queue_set_attach_date(self, enable): self.task_queue.put(("SET_DATE", enable))
    def queue_set_attach_time(self, enable): self.task_queue.put(("SET_TIME", enable))
    def queue_set_attach_increment(self, enable): self.task_queue.put(("SET_INC", enable))
    def queue_set_inc_num(self, val): self.task_queue.put(("SET_INC_N", val))
    def queue_set_inc_digits(self, val): self.task_queue.put(("SET_INC_D", val))
    def queue_set_date_fmt(self, fmt): self.task_queue.put(("SET_DATE_F", fmt))
    def queue_set_time_fmt(self, fmt): self.task_queue.put(("SET_TIME_F", fmt))
    def queue_get_example_name(self): self.task_queue.put(("GET_EXAMPLE_NAME",))
    def queue_poll_temp(self): self.task_queue.put(("POLL_TEMP",))
    
    def stop(self):
        self.running = False
        self.wait()