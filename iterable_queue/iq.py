# TODO: ensure that there is a clean exit if the user of IterableQueue does 
# not close the queue (which happens, e.g., if there's an exception outside 
# of IterableQueue).

from Queue import Empty
from multiprocessing import Queue, Pipe, Process
import time

OPEN = 0
CLOSED = 1
ADD_PRODUCER = 2
ADD_CONSUMER = 3


class IterableQueueException(Exception):
	pass
class ProducerQueueClosedException(IterableQueueException):
	pass
class ConsumerQueueClosedException(IterableQueueException):
	pass
class IterableQueueIllegalStateException(IterableQueueException):
	pass
class Done(IterableQueueException):
	pass


class Signal(object):
	pass
class CloseSignal(Signal):
	pass
class ProducerQueueCloseSignal(CloseSignal):
	pass
class ConsumerQueueCloseSignal(CloseSignal):
	pass
class IterableQueueCloseSignal(CloseSignal):
	'''
	Used by the parent process to notify the manager_process that
	The IterableQueue is closed and will not issue any more
	ProducerQueues or ConsumerQueues.

	Later used by the manager_process to notify the parent process that
	all ProducerQueues and ConsumerQueues have closed, so that all
	Queues are empty.
	'''
	pass
class AllowDelegation(Signal):
	pass



class IterableQueue(object):

	def __init__(self, maxsize=0):
		self._queue = Queue(maxsize)
		self._consumers2manager_signals = Queue()
		self._manage_pipe_local, self._manage_pipe_remote = Pipe()

		# Start the manage_queue process
		self.management_process = Process(
			target=manage_queue,
			args = (
				self._queue,
				self._consumers2manager_signals,
				self._manage_pipe_remote
			)
		)
		self.management_process.start()

	def get_producer(self):
		self._manage_pipe_local.send(ADD_PRODUCER)
		return ProducerQueue(self._queue)

	def get_consumer(self):
		self._manage_pipe_local.send(ADD_CONSUMER)
		return ConsumerQueue(self._queue, self._consumers2manager_signals)

	def close(self):
		self._manage_pipe_local.send(IterableQueueCloseSignal())


def manage_queue(
	queue,
	consumers2manager_signals,
	management_signals
):

	num_consumers = 0
	num_producers = 0

	# As long as the ManagedQueue is "open", the management process
	# listens for updates about adding new producers and consumers.  The
	# producers and consumers can actively share data over the underlying
	# queue during this time.
	status = OPEN
	while status == OPEN:
		message = management_signals.recv()
		if message == ADD_PRODUCER:
			num_producers += 1
		elif message == ADD_CONSUMER:
			num_consumers += 1
		elif isinstance(message, IterableQueueCloseSignal):
			status = CLOSED
		else:
			raise IterableQueueIllegalStateException(
				'Got unexpected signal on consumers2manager_signals: %s' % message
			)

	# We will end up here once the ManagedQueue has been closed.  Now
	# we monitor the consumers2manager_signals queue, and wait until we
	# see as many `CLOSE_SIGNALS` as there were *producers*
	# (By way of explanation: the producers put `CLOSE_SIGNALS`, directly
	# onto the working queue, so it is the consumers who receive the
	# `CLOSE_SIGNALS`, and they forward them to the manager using the
	# `consumer2manager_signals` queue.  This is necessary because:
	#
	# 1) Directly forwarding CLOSE_SIGNALS from producers to the manager
	# 	using a dedicated producers2manager_signals queu will not
	#	synchronize with the working queue: it is possible the manager
	#	would receive a producer's CLOSE_SIGNAL over the
	#	producers2manager_signals before that producer's last bit of
	#	addition to the working queue was flushed, which could mean that
	#	items get lost.
	#
	# 2) Having the manager watch the working queue for CLOSE_SIGNALs itself
	#	would require that it inspect, everything that passes through the
	#	queue, meaning it would need to take things off a queue shared
	#	with producers, then add it to a queue shared with consumers,
	#	which makes for a lot of unnecessary copying and would probably
	#	become a bottleneck.
	#
	while num_producers > 0:
		signal = consumers2manager_signals.get()

		if not isinstance(signal, ProducerQueueCloseSignal):
			raise IterableQueueIllegalStateException(
				'Got unexpected signal on consumers2manager_signals: %s'
				% str(type(signal))
			)

		num_producers -= 1

	# We will end up here once all of the producers are done.  Now we
	# send out as many "close" signals, to the consumers, as there
	# consumers.  We send them over the normal working queue to maintain
	# synchronization with work that may have been put on the queue just
	# before the last producer finished, and which might still be waiting
	# to be flushed.

	#First, wait a small amount of time to explicitly
	# give such hypothetical work time to flush
	time.sleep(0.001)
	for consumer in range(num_consumers):
		queue.put(ConsumerQueueCloseSignal())

	# Now, we wait for the ConsumerQueues to confirm that they have
	# closed.  This could take awhile, because there may have been a lot
	# of work in the working queue when the the initial
	# ConsumerQueueCloseSignals were sent out to the ConsumerQueues.
	while num_consumers > 0:
		signal = consumers2manager_signals.get()
		if not isinstance(signal, ConsumerQueueCloseSignal):
			raise IterableQueueIllegalStateException(
				'Got unexpected signal on consumers2manager_signals: %s'
				% str(type(signal))
			)
		num_consumers -= 1

	# Finally let the parent process know that everything was processed
	# successfully.  This makes it possible to call `join` in the
	# parent process.
	management_signals.send(IterableQueueCloseSignal())



#def setup_delegation(delegator, delegatee, method, before_delegation=None):
#	'''
#	Adds a callable named by `method` to delegator, which calls `method`
#	on delegatee, passing it all the arguments, and returning the result.
#	Provides an easy way for a wrapper class to expose methods of
#	an underlying class based on the method's name.
#	'''
#
#	# Define a delegation function that captures `method` in a closure.
#	# and calls `method` on the delegatee, passing all arguments through.
#	# However, before calling `method` on the delegatee, the delegator is
#	# given the opportunity to yield
#	def delegate(*args, **kwargs):
#		if before_delegation is not None:
#			preempt = getattr(delegator, before_delegation)(
#				method, *args, **kwargs
#			)
#			if not isinstance(preempt, AllowDelegation):
#				return preempt
#		return getattr(delegatee, method)(*args, **kwargs)
#
#	# Add a callable to delegator, called `method`, which calls the
#	# delegation function, which as seen above, calls the method on
#	# the delegatee.
#	setattr(delegator, method, delegate)


class ConsumerQueue(object):

	slept = False

	def __init__(self, queue, consumers2manager_signals):
		'''
		INPUTS

		* queue [multiprocessing.Queue]:  A queue that serves as the
			underlying queue for sharing arbitrary messages between
			producer and consumer processes

		* consumers2manager_signals [multiprocessing.Queue]: A special
			queue used
			for communication with the management process spawned by an
			IterableQueue process that keeps track of how many alive
			producers and consumers there are.  Used to receive a signal
			from the management process that no more work will be
			added to the queue.

		'''

		# Register parameters to the local namespace
		self.queue = queue
		self.consumers2manager_signals = consumers2manager_signals

		# Initialize status as OPEN
		self.status = OPEN


	def __iter__(self):
		return self


	def next(self, timeout=None):
		'''
		Get the next element from the queue.  If no more elements
		are expected, then raise StopIteration; otherwise if no elements 
		are available element, wait timeout seconds, before raising Empty.  
		'''
		try:
			return self.get(timeout=timeout)
		except Done:
			raise StopIteration

	# Delegate a bunch of functions to the underlying queue, but
	# always check first that `self` is open, raising
	# `ProducerQueueClosedException` if not
	def qsize(self, *args, **kwargs):
		self.raise_if_not_open('qsize')
		return self.queue.qsize(*args, **kwargs)
	def empty(self, *args, **kwargs):
		self.raise_if_not_open('empty')
		return self.queue.empty(*args, **kwargs)
	def full(self, *args, **kwargs):
		self.raise_if_not_open('full')
		return self.queue.full(*args, **kwargs)

	# Don't allow put and put_nowait to be called on ProducerQueues
	def put(self, *args, **kwargs):
		raise NotImplementedError('`ConsumerQueues`s cannot `put()`.')
	def put_nowait(self, *args, **kwargs):
		raise NotImplementedError('`ConsumerQueue`s cannot `get_nowait()`.')


	def raise_if_not_open(self, method):
		if self.status == CLOSED:
			raise ConsumerQueueClosedException(
				'`%s` cannot be called on a closed ConsumerQueue.' % method
			)


	def get_nowait(self):
		return self.get(block=False)


	def get(self, block=True, timeout=None):

		if self.status == CLOSED:
			raise Done(
				'No more items in queue, and all item producers are closed'
			)

		got_return_val = False
		while not got_return_val:

			# This can raise `Empty`, which is a desired effect.
			return_val = self.queue.get(block, timeout)

			# If we get a signal that a producer queue is closing, forward
			# it to the manager.
			if isinstance(return_val, ProducerQueueCloseSignal):
				self.consumers2manager_signals.put(return_val)

			# If we got a signal that this ConsumerQueue should close,
			# se the status to `CLOSED`, and raise the
			# ConsumerQueueClosedException.
			elif isinstance(return_val, ConsumerQueueCloseSignal):
				self.close()
				raise Done(
					'No more items in queue, and all item producers are '
					'closed'
				)

			# Otherwise indicate that we got an ordinary return val from
			# the queue
			else:
				got_return_val = True

		# Return the item from the queue
		return return_val


	def close(self):
		# Calling `close` multiple times should have no effect
		if self.status == CLOSED:
			return

		# Set status to `CLOSED`, and send a signal to the management
		# process indicating the ConsumerQueue was closed
		self.status = CLOSED
		self.consumers2manager_signals.put(ConsumerQueueCloseSignal())


	def __del__(self):
		try:
			time.sleep(0.0001)
		except AttributeError:
			pass





class ProducerQueue(object):

	def __init__(self, queue):
		self.queue = queue
		self.status = OPEN


	# Delegate a bunch of functions to the underlying queue, but
	# always check first that `self` is open, raising
	# `ProducerQueueClosedException` if not
	def qsize(self, *args, **kwargs):
		self.raise_if_not_open('qsize')
		return self.queue.qsize(*args, **kwargs)
	def empty(self, *args, **kwargs):
		self.raise_if_not_open('empty')
		return self.queue.empty(*args, **kwargs)
	def full(self, *args, **kwargs):
		self.raise_if_not_open('full')
		return self.queue.full(*args, **kwargs)
	def put(self, *args, **kwargs):
		self.raise_if_not_open('put')
		return self.queue.put(*args, **kwargs)
	def put_nowait(self, *args, **kwargs):
		self.raise_if_not_open('put_nowait')
		return self.queue.put_nowait(*args, **kwargs)


	# Don't allow get and get_nowait to be called on ProducerQueues
	def get(self, *args, **kwargs):
		raise NotImplementedError('`ProducerQueue`s cannot `get()`.')
	def get_nowait(self, *args, **kwargs):
		raise NotImplementedError('`ProducerQueue`s cannot `get_nowait()`.')


	def raise_if_not_open(self, method):
		if self.status == CLOSED:
			raise ProducerQueueClosedException(
				'`%s` cannot be called on a closed ProducerQueue.' % method
			)


	def close(self):

		# Calling `close` multiple times should have no effect
		if self.status == CLOSED:
			return

		# Set status to `CLOSED`, and send a signal to the management
		# process indicating the ProducerQueue was closed
		self.status = CLOSED
		self.queue.put(ProducerQueueCloseSignal())
