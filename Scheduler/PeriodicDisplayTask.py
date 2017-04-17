import threading
import time
import json
from DataAccess import DBA, DAO
from Config import Config
from DeviceCom import MessageHandler, DisplayController


class PeriodicDisplayTask(threading.Thread):
    def __init__(self):
        """
        Display event scheduler - periodically read tasks from task file (JSON) and schedule events
        Read data from DB >> render plot >> convert plot to standard format (display size ong or byte array) >> 
            >> obtain MQTT connection from MessageHandler >> pass data to Display controller >> 
            >> [DisplayController] convert image to line format >> [DisplayController] transmit via MQTT
        """
        threading.Thread.__init__(self)
        self.conf = Config.Config().get_config()
        self.schedule_file_name = self.conf.get('scheduler', 'task_file')
        self.interval = self.conf.get('scheduler', 'schedule_interval')
        self.screen_index = {}  # help with screen rotation
        self.last_time = time.time()
        self.db = DBA.Dba(self.conf.get('db', 'path'))

    def _do_task(self, task_json):
        """
        Get display from DB, prepare data and send to device via MQTT
        :param task_json: 
        :return: 
        """
        device_id = task_json.get('device_id')
        display_name = task_json.get('display_name')

        screens = self.db.get_display(device_id, display_name)  # all screen from single display
        screen = None  # current screen

        # rotates between all display screen
        if str.format('{};{}', device_id, display_name) in self.screen_index:
            current_index = self.screen_index[device_id + ';' + display_name] + 1 if \
                (self.screen_index[device_id + ';' + display_name] + 1) < len(screens) else 0
            self.screen_index[device_id + ';' + display_name] = current_index

            screen = screens[current_index]
        else:  # new screen task
            self.screen_index[device_id + ';' + display_name] = 0
            screen = screens[0]

        mqtt_handler = MessageHandler.MessageHandler(self.conf.get('mqtt', 'ip'), self.conf.get('mqtt', 'port'))
        display_controller = DisplayController.DisplayController(mqtt_handler.get_client_instance(),
                                                                 str.format("{}/{}/{}",
                                                                            self.conf.get('mqtt', 'base_msg'),
                                                                            device_id, display_name))
        # TODO magic with generating plot and sending to MQTT
        # display_controller.draw_bitmap()

    def run(self):
        """
        Every schedule_interval starts all pending tasks
        :return: 
        """
        while True:
            tasks_json = None
            with open(self.schedule_file_name, 'r') as file:  # load task JSON
                try:
                    tasks_json = json.loads(file.read())
                except IOError:
                    print("Error cant read scheduler file")
                except json.JSONDecodeError:
                    print("Error cant convert JSON file")

            time_now = time.time()
            for task in tasks_json:  # check if the task is ready to run
                if time_now >= self.last_time + (task.get('interval', 0) * 1000):
                    self._do_task(task)
            self.last_time = time_now

            time.sleep(self.interval)
