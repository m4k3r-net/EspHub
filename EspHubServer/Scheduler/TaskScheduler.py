from DataAccess import DAO, DAC, DBA
from Scheduler import DisplayInitHandler
from Tools import Log
from datetime import datetime, timedelta
from multiprocessing import Event, Process, active_children, Queue
from DeviceCom.MessageHandler import MessageHandler
from Config.Config import Config
import time
import random

log = Log.Log.get_logger()
conf = Config.get_config()

# Dictionary of initialization functions - key = task type, value = initialization function
# Initialization function must accept dictionary of arguments and return list of ScheduledTask objects
# example: init(args) -> Scheduler.ScheduledTask
task_init_handlers = {
	DAO.Task.TYPE_DISPLAY: DisplayInitHandler.init,  # handle display scheduler events initialization
}


class TaskScheduler(Process):
	def __init__(self):
		super().__init__()
		self.tasks = []
		self._next_task = None
		self.end_event = Event()

		self.init_scheduled_tasks()

	def stop(self):
		"""
		Stop task processing and end task process.
		:return:
		"""
		log.info("Terminating scheduled task processing.")
		self.end_event.set()

	def init_scheduled_tasks(self):
		"""
		Initialize tasks from database using type specific init functions.
		:return:
		"""
		with DAC.keep_weak_session() as db:
			tasks = DBA.get_active_tasks(db)

		for task in tasks:
			task_init_handler = task_init_handlers.get(task.type)
			task_group_id = task.group_id

			if task_init_handler:
				new_sch_tasks = task_init_handler(task.params)
				# new_sch_tasks = []
				for sch_task in new_sch_tasks:
					sch_task.group_id = task_group_id  # add group ID to new ScheduledTask object
				self.tasks += new_sch_tasks

			else:
				log.error("Unknown task init function for task type '{}'.".format(task.type))

		for sch_task in self.tasks:
			# schedule first run with random jitter (0.3-3 s) which prevent overlapping of task starts
			sch_task.next_run = datetime.now() + timedelta(0, sch_task.interval) + timedelta(0, sch_task.start_offset) + timedelta(milliseconds=random.randint(300, 3000))
			log.debug("Task '{} (G:{})' is scheduled on {}.".format(sch_task.task_type, sch_task.group_id, sch_task.next_run))

	def _find_next_task(self):
		"""
		Find next task tu run.
		:return:
		"""
		self.tasks = sorted(self.tasks, key=lambda task: task.next_run)
		self._next_task = self.tasks[0] if self.tasks else None

	def _get_time_to_next_task(self):
		"""
		Calculate sleep time to nex task.
		:return:
		"""
		if self._next_task:
			sleep_time = self._next_task.next_run - datetime.now()
			sleep_time_seconds = sleep_time.seconds + (sleep_time.microseconds / 1000000)
			return sleep_time_seconds if sleep_time_seconds > 0 else 0
		else:
			return 10  # if there is no task sleep 10s

	def mqtt_queue(self, queue, event):
		"""
		Collect messages from mqtt queue and send them as MQTT message
		Mqtt message object is dictionary in format:
		{'topic': 'esp_hub/...', 'payload': 'message to send', 'qos': 0}
		:param queue: Multiprocessing queue.
		:type queue: Queue
		:param event: Multiprocessing event which indicate end of processing.
		:type event: Event
		:return:
		"""
		mqtt = MessageHandler(conf.get('mqtt', 'ip'), conf.getint('mqtt', 'port'))

		while not event.is_set():
			msg_obj = queue.get()
			if msg_obj:
				# send message from task worker to MQTT
				try:
					log.debug("Sending MQTT ({} bytes) response from scheduled worker.".format(len(msg_obj['payload'])))
					mqtt.publish(msg_obj['topic'], msg_obj['payload'], int(msg_obj.get('qos', 0)))
				except KeyError:
					log.error("Scheduled worker response is in invalid format - missing keys 'topic' or 'payload'.")

	def _get_task(self):
		"""
		Check if next_task is ready, if yes return it and schedule next repeating.
		:return: ScheduledTask object.
		:rtype: ScheduledTask
		"""
		if self._next_task.next_run > datetime.now():
			log.warning("Task is not ready yet. Internal error.")
			return None

		if self._next_task.repeating:
			self._next_task.next_run = datetime.now() + timedelta(0, self._next_task.interval)
			log.debug("Task '{} (G:{})' is scheduled on {}.".format(self._next_task.task_type, self._next_task.group_id, self._next_task.next_run))
		else:
			self.tasks.remove(self._next_task)

		return self._next_task

	def run(self):
		"""
		Start task processing until end_event is set.
		Each task are spawned in separate process.
		"""
		# create queue for mqtt messages
		queue = Queue(maxsize=10)
		queue_worker = Process(target=self.mqtt_queue, name='Queue worker', kwargs={'queue': queue, 'event': self.end_event})
		queue_worker.start()

		while not self.end_event.is_set():
			time.sleep(0.05)
			self._find_next_task()
			task = self._get_task()

			if task:
				task.kwargs['queue'] = queue
				process = Process(target=task.event, kwargs=task.kwargs,
								  name="{} (G:{})".format(task.task_type, task.group_id))
				process.start()

			# check and join running children
			running_processes = active_children()
			if len(running_processes) > 3:
				log.warning(
					"Too many running task processes: {} (count: {})".format([p.name for p in running_processes],
																			 len(running_processes)))

			sleep = self._get_time_to_next_task()
			self.end_event.wait(sleep)  # wait until next task or undil end_event is set

		# wait 5 seconds for children (10 * 0.5), if there is no children break loop
		for _ in range(10):
			children = active_children()
			if len(children) > 1:
				log.debug("Waiting for active children: {}.".format([p.name for p in children]))
				time.sleep(0.5)
			else:
				log.debug("No active children.")
				break

		# close and join queue for mqtt messages
		queue.put(None)  # put empty message to queue to unlock qet waiting
		queue.close()
		queue.join_thread()
		queue_worker.join()

		log.debug("Scheduled task processing terminated.")
