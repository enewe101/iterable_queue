from __future__ import division
from __future__ import print_function
from __future__ import absolute_import
from future import standard_library
standard_library.install_aliases()
from builtins import range
from past.utils import old_div
from collections import Counter
from unittest import main, TestCase
from iterable_queue.iq import (
	_manage, ADD_PRODUCER, ADD_CONSUMER, CLOSED, ProducerQueue,
	ConsumerQueue, ProducerQueueClosedException, IterableQueueCloseSignal, 
	ProducerQueueCloseSignal, ConsumerQueueCloseSignal, 
	ConsumerQueueClosedException, IterableQueue, Done, READY
)
from multiprocessing import Queue, Pipe, Process
from queue import Empty
import time
import random



class TestIterableQueue(TestCase):

	def test_simple(self):
		'''
		Does a basic test of the queue functionality, by creating two
		producer queues and one consumer queue, adding to the producer
		queues and then consuming from the consumer queue using the
		iteration idiom.  This test doesn't use multiprocessing.
		'''

		messages1 = list(range(10))
		messages2 = list(range(10, 20))
		messages = messages1 + messages2

		iq = IterableQueue()

		consumer = iq.get_consumer()

		producer1, producer2 = iq.get_producer(), iq.get_producer()

		# We're done getting producers and consumers
		iq.close()

		for i in messages1:
			producer1.put(i)
		producer1.close()

		for i in messages2:
			producer2.put(i)
		producer2.close()

		messages_received = []
		for i in consumer:
			messages_received.append(i)

		self.assertEqual(messages_received, messages)


	def test_close_queue_after_producers(self):
		'''
		this test is very similar to the one above, the only difference
		being that we close the IterableQueue after closing all of the
		producers.  We should be able to close them in any order
		'''

		messages1 = list(range(10))
		messages2 = list(range(10, 20))
		messages = messages1 + messages2

		iq = IterableQueue()

		consumer = iq.get_consumer()

		producer1, producer2 = iq.get_producer(), iq.get_producer()


		for i in messages1:
			producer1.put(i)
		producer1.close()

		for i in messages2:
			producer2.put(i)
		producer2.close()

		# We're done getting producers and consumers
		iq.close()

		messages_received = []
		for i in consumer:
			messages_received.append(i)

		self.assertEqual(messages_received, messages)


	def test_multiprocessing(self):

		num_producers = 10
		num_consumers = 7

		# Define a function for producers.  They put their worker
		# ID onto the queue, repeatedly.
		def produce(queue, worker_id, num_to_produce):
			for i in range(num_to_produce):
				time.sleep(old_div(random.random(),100.0))
				queue.put(worker_id)

			queue.close()

		# Define a function for processes that act as consumers relative
		# to one queue, and producers relative to another.  This
		# enables testing having multiple concurrent consumers.
		# These workers just pick elements off the first queue and put
		# them onto the second, using the iteration idiom.
		def handoff(incoming_queue, outgoing_queue):
			for i in incoming_queue:
				outgoing_queue.put(i)

			outgoing_queue.close()

		iq_step1 = IterableQueue()
		iq_step2 = IterableQueue()

		# Start a bunch of producers
		for producer_id in range(1, num_producers+1):
			num_to_produce = producer_id
			Process(target=produce, args=(
				iq_step1.get_producer(), producer_id, num_to_produce
			)).start()

		# Start a bunch of consumer-producers
		for consumer_id in range(1, num_consumers+1):
			Process(target=handoff, args=(
				iq_step1.get_consumer(), iq_step2.get_producer()
			)).start()

		# Finally we'll pull all the results aggregated on the
		# second Iterable_queue
		aggregated_queue = iq_step2.get_consumer()

		# Close the queues to indicate that no more producers or
		# consumers will be made
		iq_step1.close()
		iq_step2.close()

		# Iterate over the contents of the aggregated_queue
		counter = Counter()
		for i in aggregated_queue:
			counter[i] += 1

		# Finally, let's make sure that we actually got everything
		# We expected.  Each producer was given an id from 1 to
		# num_producers+1, and was told to put its id onto the producer
		# queue a number of times equal to its id.  I.e. we should find
		# one 1, two 2s, three 3s, etc.
		for i in range(1, num_producers+1):
			self.assertEqual(i, counter[i])



class TestManageQueue(TestCase):

	def test_manage(self):

		# Define some constants used in the test
		num_producers = 7
		num_consumers = 11
		poll_timeout = 2

		# Make some queues and pipes to simulate the scenario of a
		# ManagedQueue
		working_queue = Queue()
		manage_queue = Queue()

		# Make and start a manage process
		manage_process = Process(
			target=_manage, args=(working_queue, manage_queue))
		manage_process.start()

		# Immediately take the ready signal
		self.assertTrue(manage_queue.get() == READY)
		manage_queue.put(READY)

		# Simulate issuing several producer and consumer processes
		# and then closing the ManagedQueue
		for producer in range(num_producers):
			manage_queue.put(ADD_PRODUCER)
		for consumer in range(num_consumers):
			manage_queue.put(ADD_CONSUMER)
		manage_queue.put(IterableQueueCloseSignal())

		# At this point the manage_process should be alive and waiting for us
		# to send `num_producers` number of `ProducerQueueCloseSignal`s on the
		# manage_queue.  Once it recieves that, it will "notify" all the
		# consumers and close.  So we check that it doesn't close prematurely,
		# but does close once we've sent enough signals.
		for producer in range(num_producers):
			self.assertTrue(manage_process.is_alive())
			manage_queue.put(ProducerQueueCloseSignal())

		# Check that num_consumer `ConsumerQueueCloseSignal`s are sent on
		# the working_queue.  Meanwhile, simulate the ConsumerQueue
		# recieving these signals: they respond by closing themselves and
		# echoing back a `ConsumerQueueCloseSignal` over the
		# manage_queue
		for consumer in range(num_consumers):
			self.assertTrue(isinstance(
				working_queue.get(timeout=2), ConsumerQueueCloseSignal
			))
			manage_queue.put(ConsumerQueueCloseSignal())


class TestConsumerQueue(TestCase):

	def test_iteration(self):

		queue = Queue()
		manage_queue = Queue()
		consumer_queue = ConsumerQueue(queue, manage_queue)
		messages = list(range(10))
		queue_timeout = 0.1

		# First, put several elements onto the queue
		for message in messages:
			queue.put(message)

		# Then put a message telling the ConsumerQueue to close
		queue.put(ConsumerQueueCloseSignal())

		# It should be possible to simply treat the consumer queue as
		# an iterator, which will raise StopIteration once the Consumer
		# Queue is closed
		messages_seen = []
		for message in consumer_queue:
			messages_seen.append(message)

		# We should see all the messages, but the ConsumerQueueCloseSignal
		# should have been removed and interpreted transparently
		self.assertEqual(messages_seen, messages)

		# Give time for the queue to flush (normally manager process does this)
		time.sleep(0.1)


	def test_closure(self):

		work_queue = Queue()
		manage_queue = Queue()
		consumer_queue = ConsumerQueue(work_queue, manage_queue)
		messages = list(range(10))
		queue_timeout = 0.1

		# First, put several elements onto the work_queue
		for message in messages:
			work_queue.put(message)

		# The consuer_queue should be able to get all the messages
		for message in messages:
			self.assertEqual(
				consumer_queue.get(timeout=queue_timeout), message
			)

		# Now put a ProducerQueueCloseSignal on the work_queue, followed
		# by more messages
		work_queue.put(ProducerQueueCloseSignal())
		for message in messages:
			work_queue.put(message)

		# Pulling the messages off the work_queue, we should find that the
		# Consumer work_queue steps transparently over the ProducerQueueClose
		# Signal, so we will not see it as we iterate over the work_queue
		for message in messages:
			self.assertEqual(
				consumer_queue.get(timeout=queue_timeout), message
			)
		# And the work_queue is now empty
		with self.assertRaises(Empty):
			consumer_queue.get(timeout=queue_timeout)

		# But the ProducerQueueCloseSignal was indeed silently seen by
		# the ConsumerQueue, and was added to the manage_queue
		# work_queue
		self.assertTrue(isinstance(
			manage_queue.get(timeout=queue_timeout),
			ProducerQueueCloseSignal
		))

		# We'll now add more items to the work_queue, followed by simulating
		# a ConsumerQueueCloseSignal being sent to the ConsumerQueue
		# on the working_queue, which should cause it to raise
		# ConsumerQueueClosedException once get is called and the
		# ConsumerQueueCloseSingal is recieved
		for message in messages:
			work_queue.put(message)
		work_queue.put(ConsumerQueueCloseSignal())
		for message in messages:
			self.assertEqual(
				consumer_queue.get(timeout=queue_timeout), message
			)
		with self.assertRaises(Done):
			val = consumer_queue.get(timeout=queue_timeout)

		# At this point the consumer work_queue should have echoed back
		# `ConsumerQueueCloseSignal`s over the manage_queue
		# work_queue
		self.assertTrue(isinstance(
			manage_queue.get(timeout=queue_timeout),
			ConsumerQueueCloseSignal
		))



	def test_delegation(self):

		queue = Queue()
		manage_queue = Queue()
		consumer_queue = ConsumerQueue(queue, manage_queue)
		message = 'yo'
		queue_timeout = 0.1

		# The consumer_queue does not implement `put()`
		with self.assertRaises(NotImplementedError):
			consumer_queue.put()
		with self.assertRaises(NotImplementedError):
			consumer_queue.put_nowait()

		# There is still no message is on the queue
		with self.assertRaises(Empty):
			queue.get(timeout=queue_timeout)

		# The consumer_queue does implement `get`
		queue.put(message)
		self.assertEqual(consumer_queue.get(timeout=queue_timeout), message)
		queue.put(message)
		time.sleep(queue_timeout)
		self.assertEqual(consumer_queue.get_nowait(), message)
		queue.put(message)
		time.sleep(queue_timeout)
		self.assertEqual(consumer_queue.get(block=False), message)

		# The next three assertions test that Empty is raised for various
		# kinds of `get` call
		with self.assertRaises(Empty):
			consumer_queue.get(timeout=queue_timeout)

		with self.assertRaises(Empty):
			consumer_queue.get_nowait()

		with self.assertRaises(Empty):
			consumer_queue.get(block=False)

		# The next three assetions check that calls which return information
		# return the same values when called on ProducerQueue as on Queue
		# The first test is a bit of an exception:
		# Queue.qsize() may raise a NotImplementedError, if so, just make
		# sure that ProducerQueue does too.  Otherwise, make sure they
		# return the same value.
		try:
			queue.qsize()
		except NotImplementedError:
			with self.assertRaises(NotImplementedError):
				consumer_queue.qsize()
		else:
			self.assertEqual(consumer_queue.qsize(), queue.qsize())

		self.assertEqual(consumer_queue.empty(), queue.empty())
		self.assertEqual(consumer_queue.full(), queue.full())


class TestProducerQueue(TestCase):

	def test_closure(self):

		queue = Queue()
		producer_queue = ProducerQueue(queue)
		message = 'yo'
		queue_timeout = 0.1

		# While the ProducerQueue is open, we can put things
		producer_queue.put(message)

		# Close the ProducerQueue
		producer_queue.close()

		# Now we should find that a ProducerQueueCloseSignal was placed on
		# the working queue.  First take the message off that was put
		# on before the producer_queue was closed.
		self.assertEqual(queue.get(timeout=queue_timeout), message)
		self.assertTrue(isinstance(
			queue.get(timeout=queue_timeout),
			ProducerQueueCloseSignal
		))

		# Attempting to put something on the closed ProducerQueue raises
		# an exception.  It should not put anything onto the queue which
		# we will test in a moment
		with self.assertRaises(ProducerQueueClosedException):
			producer_queue.put(message)

		# No message was placed on the underlying queue
		with self.assertRaises(Empty):
			queue.get(timeout=queue_timeout)

		# calling `ProducerQueue.close()` again is not an error.
		producer_queue.close()

		# But it doesn't cause a `ProducerQueueCloseSignal` to be placed on
		# the working queue this time, so the working queue is empty.
		with self.assertRaises(Empty):
			queue.get(timeout=queue_timeout)


	def test_ProducerQueue_delegation(self):

		queue = Queue()
		producer_queue = ProducerQueue(queue)
		message = 'yo'
		queue_timeout = 0.1


		# The producer_queue does not implement `get()`
		queue.put(message)
		with self.assertRaises(NotImplementedError):
			producer_queue.get()

		with self.assertRaises(NotImplementedError):
			producer_queue.get_nowait()

		# The message is still on the queue
		self.assertTrue(queue.get(timeout=queue_timeout), message)

		# The producer_queue does implement `put`
		producer_queue.put(message)
		self.assertEqual(queue.get(), message)

		producer_queue.put_nowait(message)
		self.assertEqual(queue.get(), message)

		# Tests below are commented out because `get()` has been removed
		# from the implementation of ProducerQueue to preserve signaling and
		# management semantics.
		#
		# The next three assertions test that Empty is raised for various
		# kinds of `get` call
		#with self.assertRaises(Empty):
		#	producer_queue.get(timeout=queue_timeout)
		#
		#with self.assertRaises(Empty):
		#	producer_queue.get_nowait()
		#
		#with self.assertRaises(Empty):
		#	producer_queue.get(block=False)

		# The next three assetions check that calls which return information
		# return the same values when called on ProducerQueue as on Queue
		# The first test is a bit of an exception:
		# Queue.qsize() may raise a NotImplementedError, if so, just make
		# sure that ProducerQueue does too.  Otherwise, make sure they
		# return the same value.
		try:
			queue.qsize()
		except NotImplementedError:
			with self.assertRaises(NotImplementedError):
				producer_queue.qsize()
		else:
			self.assertEqual(producer_queue.qsize(), queue.qsize())

		self.assertEqual(producer_queue.empty(), queue.empty())
		self.assertEqual(producer_queue.full(), queue.full())




if __name__ == '__main__':
	main()
