class ScheduledTask(object):
	def __init__(self, task_type, interval, event, name='', start_offset=0, kwargs=None, group_id=None, repeating=True):
		"""
		Init scheduled task.
		:param task_type: Type of task.
		:param interval: Scheduled interval in seconds.
		:param event: Function which will be fired on schedule. Function MUST accept argument queue (mqtt queue) and all kwargs arguments! Example: func(queue, my_kwarg_arg)
		:param name: Custom task name for logging.
		:param start_offset: Time in seconds for which will be scheduled task delayed after start.
		:param kwargs: Arguments for event which are pass as kwargs (non-positional based on name).
		:param group_id: Specific group ID.
		:param repeating: Is repeating enabled.
		"""
		self.task_type = task_type
		self.interval = interval
		self.event = event
		self.name = name if name else task_type
		self.start_offset = start_offset
		self.kwargs = kwargs
		self.group_id = group_id
		self.repeating = repeating
		self.next_run = None

	def __str__(self):
		return str(self.__dict__)
