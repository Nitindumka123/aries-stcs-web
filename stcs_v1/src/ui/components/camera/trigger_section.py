# src/ui/components/camera/trigger_section.py
from PyQt6.QtWidgets import QWidget, QGridLayout, QLabel, QComboBox, QFrame

class TriggerInSection(QWidget):
    """
    UI for managing External Trigger Input settings.
    Includes conditional display for Polarity (Trigger Determined By).
    """
    def __init__(self, worker):
        super().__init__()
        self.worker = worker
        self.init_ui()

    def init_ui(self):
        self.layout = QGridLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)

        # Trigger In
        self.layout.addWidget(QLabel("Trigger In:"), 0, 0)
        self.combo_trigger_in = QComboBox()
        self.combo_trigger_in.addItems(["No Response", "Readout Per Trigger"])
        self.combo_trigger_in.currentTextChanged.connect(self.on_trigger_changed)
        self.layout.addWidget(self.combo_trigger_in, 0, 1)

        # Trigger Determined By (Polarity)
        self.lbl_determined_by = QLabel("Trigger Determined By:")
        self.combo_determined_by = QComboBox()
        self.combo_determined_by.addItems(["Negative Polarity", "Positive Polarity"])
        self.combo_determined_by.currentTextChanged.connect(self.on_determination_changed)
        
        self.layout.addWidget(self.lbl_determined_by, 1, 0)
        self.layout.addWidget(self.combo_determined_by, 1, 1)

        # Initially hide the polarity option
        self.show_determination(False)

    def update_trigger_options(self, readout_mode):
        """Dynamic Trigger validation based on Readout Mode."""
        current_trigger = self.combo_trigger_in.currentText()
        
        self.combo_trigger_in.blockSignals(True)
        self.combo_trigger_in.clear()
        
        options = ["No Response", "Readout Per Trigger"]
        if readout_mode == "Kinetics":
            options.append("Shift Per Trigger")
            
        self.combo_trigger_in.addItems(options)
        
        if current_trigger in options:
            self.combo_trigger_in.setCurrentText(current_trigger)
        else:
            self.combo_trigger_in.setCurrentText("No Response")
            
        self.combo_trigger_in.blockSignals(False)
        self.on_trigger_changed(self.combo_trigger_in.currentText())

    def on_trigger_changed(self, text):
        self.worker.queue_set_trigger_response(text)
        # Only show Polarity if not "No Response"
        self.show_determination(text != "No Response")

    def on_determination_changed(self, text):
        self.worker.queue_set_trigger_determination(text)

    def show_determination(self, visible):
        self.lbl_determined_by.setVisible(visible)
        self.combo_determined_by.setVisible(visible)

    def sync_ui(self):
        """Pushes current UI state to the hardware."""
        self.on_trigger_changed(self.combo_trigger_in.currentText())
        if self.combo_trigger_in.currentText() == "Readout Per Trigger":
            self.on_determination_changed(self.combo_determined_by.currentText())


class TriggerOutSection(QWidget):
    """
    UI for managing External Hardware Output Signals.
    """
    def __init__(self, worker):
        super().__init__()
        self.worker = worker
        self.init_ui()

    def init_ui(self):
        self.layout = QGridLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)

        # Output Signal
        self.layout.addWidget(QLabel("Output Signal:"), 0, 0)
        self.combo_output = QComboBox()
        self.combo_output.addItems([
            "Shutter Open",
            "Always High", 
            "Always Low", 
            "Busy", 
            "Not Reading Out", 
        ])
        self.combo_output.currentTextChanged.connect(lambda t: self.worker.queue_set_output_signal(t))
        self.layout.addWidget(self.combo_output, 0, 1)

    def sync_ui(self):
        """Pushes current UI state to the hardware."""
        self.worker.queue_set_output_signal(self.combo_output.currentText())