'''
This module contains all of the major functionality for the IterableQueue, 
including the IterableQueue class itself.  Users should create an IterableQueue
instance, and obtain producer and consumer endpoints from it by calling
IterableQueue.get_producer() and IterableQueue.get_consumer().  These yield 
instances of ProducerQueue and ConsumerQueue endpoints, respectively, which wrap 
an underlying multiprocessing.Queue.

The ProducerQueue and ConsumerQueue endpoints expose the methods of 
multiprocessing.Queue, except that the ProducerQueue cannot .get() and the 
ConsumerQueue cannot .put().
'''

# When a new IterableQueue instance is made, it spawns a manager_process
# which is in charge of keeping track of how many producer and consumer
# endpoints are still active.  This makes it possible to know when the queue
# is truly done, which means that it isn't just empty, but the producers are
# also finished adding to it.
#
# The IterableQueue wraps an underlying multiprocessing.Queue, called the
# "work_queue", which holds the items put by the producers and consumed
# by the consumers.
#
# The IterableQueue also owns a "manage_queue" that is used to keep track of how 
# many producers and consumers are still active, and to keep processes
# syncronized during initialization and teardown.  The manage_queue is used to
# signal between the main process, the manager, and the queue endpoints (which
# are typically each living in their own process).
#
# During the lifetime of the IterableQueue, the manager goes through three 
# states:
#
#    - OPEN: While the manager process is in the OPEN state, the IterableQueue
#        is able to create new producer and consumer endpoints.  So long as
#        the state remains OPEN, we can never consider the work_queue to be
#        DONE, because active producer endpoints may add more work.  In fact,
#        new producer endpoints may be added to the queue.
#
#    - CLOSED: Once the manager is CLOSED, no new endpoints can be added,
#        although there may still be many active producer and comsumer
#        endpoints.  While in this state, the manager_process waits for the
#        number of active producers to drop to zero.  At that point, nothing new
#        can be added to the work_queue.
#
#    - CLOSED and num_producers == 0:
#        Once the number of producers reaches zero, the manager process places
#        special close signals onto the work_queue, which instruct consumer
#        queues queues to raise DONE.  If consumer queues are being treated as
#        an iterable it will cause them to StopIteration.  When a ConsumerQueue
#        receives the close signal, it sends back a confirmation to the
#        manager_process confirming that it has closed.
#
#        Meanwhile, the manager waits until all consumers have closed before
#        exiting
#
#    - CLOSED and num_consumers == 0:
#        Once the number of active consumers drops to zero, the manager exits
#
# The manage_queue provides a side-channel for signalling without having the
# signals get mixed in with the application's queue submissions.  However,
# some signalling must be sent over the work_queue to ensure proper
# synchronization.
#
# For example, when a ProducerQueue closes, it should not signal directly
# To the manager over the manage_queue.  If it did that, then it's possible
# that the manager_process would get the signal before the producer's most
# recent put() had flushed.  The manager could in turn place send a close
# signal to the consumers before the last item had been put on the work_queue.
# For this reason, both the work_queue and the manager_queue are used
# for signalling, depending on whether the signal should be synchronized with
# the work_queue or not.
#
# The flow of signalling works as follows:
# While the manager_process is open, the main process (the one in which the
# IterableQueue instance was created), sends signals on the manage_queue
# telling the manager_process when new endpoints are created or destroyed.
# At some point, in the main process, IterableQueue.close() is called,
# and the main process then sends a signal on the manage_queue to the
# manager_process indicating that no new endpoints will be created.
#
# When ProducerQueue.close() is called on producer endpoints, they don't
# signal over teh manage_queue, since we need to guarantee the manager
# recievs this signal after that producer's put() on the work_queue have
# flushed.  Thereofre the producer endpoints send close signals over the 
# work_queue.
#
# Consumers watch for the producer endpoints' close signals on the work_queue
# and simply forward them to the manager over the manage queue.  This is done
# transparently so that those signals are never actually yielded to the caller
# of the consumer queue's get().
#
# Once the manager has seen enough close signals forwarded to it from consumers
# (such that it knows there are no active producers), it sends close signals
# out to the consumers over the work_queue.  These signals are guaranteed to be
# the last signals in the work_queue, because they are placed onto the
# work_queue queue after the last item from the last producer has been
# retrieved from the work_queue. The manager sends out as many signals as there
# are consumers.  and each consumer closes in response to seeing one of these
# signals.
#
# The manager stays open during this time.  Right before closing, the consumers
# send back a confirmation to the manager tha they have closed (this matters
# because if each working item takes a long time to process, they may not
# consume the close signals right away, and if the manage process closes right
# after placing the close signals on the queue, it could corrupt the queue.
# Only after seeing a confirmation from each consumer that it has closed, sent 
# over the manage_queue, does the manager finally exit.


from builtins import str
from builtins import range
from builtins import object
import sys
import signal
import atexit
from queue import Empty
from multiprocessing import Queue, Pipe, Process, Manager
import time


OPEN = 0
CLOSED = 1
ADD_PRODUCER = 2
ADD_CONSUMER = 3
READY = 4


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



class IterableQueue(object):

    def __init__(self, maxsize=0):
        manager = Manager()
        self._work_queue = manager.Queue(maxsize)
        self._manage_queue = manager.Queue()
        # Start the manage_queue process
        self._master_sync_pipe, _manager_sync_pipe = Pipe()
        self._management_process = Process(
            target=_manage, args=(
                self._work_queue, self._manage_queue, _manager_sync_pipe)
        )
        self._management_process.start()
        self._wait_until_ready()

    def _wait_until_ready(self):
        """
        This handshake-style function ensures that the manager process has had
        time to start up before the construction of the IterableQueue returns.
        That way the caller doesn't start using it before the manager is
        tracking things.  First the manager sends a READY signal, then, on a
        separate channel, this master sends it's own ready signal.  This
        function only returns once both the master and the manager have seen
        eachothers' ready signals.  Two channels are used to avoid the case
        where the manager or master tries to read it's own ready signal.
        """
        # Wait for the manager to be ready before we spawn any endpoints
        msg = self._manage_queue.get()
        if not msg == READY:
            raise SyncError('IterableQueue: manager not ready: %s' % msg)
        self._master_sync_pipe.send(READY)

    def get_producer(self):
        self._manage_queue.put(ADD_PRODUCER)
        producer_queue = ProducerQueue(self._work_queue)
        return producer_queue

    def get_consumer(self):
        self._manage_queue.put(ADD_CONSUMER)
        consumer_queue = ConsumerQueue(self._work_queue, self._manage_queue)
        return consumer_queue

    def close(self):
        self._manage_queue.put(IterableQueueCloseSignal())


def _manage(_work_queue, _manage_queue, _manager_sync_pipe):

    # Synchronize with the main process before any endpoints can be spawned
    _manage_queue.put(READY)
    if not _manager_sync_pipe.recv() == READY:
        raise IterableQueueIllegalStateException(
            'Got unexpected signal on manage_queue: %s' % message
        )

    # Keep track of how many producer and consumer endpoints are active.
    num_consumers = 0
    num_producers = 0

    # As long as the status is OPEN, the management process
    # listens for signals indicating new producer and consumer endpoints have
    # been created.  Producers and consumers can share data over the work_queue
    # during this time.
    status = OPEN
    while status == OPEN:
        message = _manage_queue.get()
        if message == ADD_PRODUCER:
            num_producers += 1
        elif message == ADD_CONSUMER:
            num_consumers += 1
        elif isinstance(message, ProducerQueueCloseSignal):
            num_producers -= 1
        elif isinstance(message, IterableQueueCloseSignal):
            status = CLOSED
        else:
            raise IterableQueueIllegalStateException(
                'Got unexpected signal on manage_queue: %s' % message
            )

    # At this point, the Iterable Queue is closed, so no more endpoints will
    # be created.  We continue to listen for producers being closed, awaiting
    # the point at which all producers are closed.  At that point, nothing more
    # can be added to the work_queue because there's no more active producers.
    while num_producers > 0:
        signal = _manage_queue.get()

        if isinstance(signal, ProducerQueueCloseSignal):
            num_producers -= 1

        else:
            raise IterableQueueIllegalStateException(
                'Got unexpected signal on manage_queue: %s'
                % str(type(signal))
            )

    # All producers are closed.  Now signal to the consumers that they should
    # close (they will only receive this signal after all working items have
    # been removed from the work_queue).
    for consumer in range(num_consumers):
        _work_queue.put(ConsumerQueueCloseSignal())

    # Listen for consumers to echo back confirmation that they have closed.
    # The manager waits to exit to make sure that the consumers get the close 
    # signals.
    while num_consumers > 0:
        signal = _manage_queue.get()
        if isinstance(signal, ConsumerQueueCloseSignal):
            num_consumers -= 1

        else:
            raise IterableQueueIllegalStateException(
                'Got unexpected signal on manage_queue: %s'
                % str(type(signal))
            )


class ConsumerQueue(object):

    def __init__(self, _work_queue, _manage_queue):
        '''
        INPUTS

        * _work_queue [multiprocessing.Queue]:  A queue that serves as the
            underlying queue for sharing arbitrary messages between
            producer and consumer processes

        * _manage_queue [multiprocessing.Queue]: A special
            queue used
            for communication with the management process spawned by an
            IterableQueue process that keeps track of how many alive
            producers and consumers there are.  Used to receive a signal
            from the management process that no more work will be
            added to the work_queue.

        '''

        # Register parameters to the local namespace
        self._work_queue = _work_queue
        self._manage_queue = _manage_queue

        # Initialize status 
        self.status = OPEN


    def __iter__(self):
        return self


    def __next__(self, timeout=None):
        return self.next(timeout)

    def next(self, timeout=None):
        '''
        Get the next element from the work_queue.  If no more elements
        are expected, then raise StopIteration; otherwise if no elements 
        are available element, wait timeout seconds, before raising Empty.  
        '''
        try:
            return self.get(timeout=timeout)
        except Done:
            raise StopIteration

    # Delegate a bunch of functions to the underlying work_queue, but
    # always check first that `self` is open, raising
    # `ProducerQueueClosedException` if not
    def qsize(self, *args, **kwargs):
        self._raise_if_not_open('qsize')
        return self._work_queue.qsize(*args, **kwargs)
    def empty(self, *args, **kwargs):
        self._raise_if_not_open('empty')
        return self._work_queue.empty(*args, **kwargs)
    def full(self, *args, **kwargs):
        self._raise_if_not_open('full')
        return self._work_queue.full(*args, **kwargs)

    # Don't allow put and put_nowait to be called on ProducerQueues
    def put(self, *args, **kwargs):
        raise NotImplementedError('`ConsumerQueues`s cannot `put()`.')
    def put_nowait(self, *args, **kwargs):
        raise NotImplementedError('`ConsumerQueue`s cannot `get_nowait()`.')

    def _raise_if_not_open(self, method):
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
            return_val = self._work_queue.get(block, timeout)

            # If we get a signal that a producer queue is closing, forward
            # it to the manager.
            if isinstance(return_val, ProducerQueueCloseSignal):
                self._manage_queue.put(return_val)

            # If we got a signal that this ConsumerQueue should close,
            # set the status to `CLOSED`, and raise the
            # ConsumerQueueClosedException.
            elif isinstance(return_val, ConsumerQueueCloseSignal):
                self.close()
                raise Done(
                    'No more items in queue, and all item producers are '
                    'closed'
                )

            # Otherwise indicate that we got an ordinary return val from
            # the work_queue
            else:
                got_return_val = True

        # Return the item from the work_queue
        return return_val


    def close(self):
        # Calling `close` multiple times should have no effect
        if self.status == CLOSED:
            return

        # Set status to `CLOSED`, and send a signal to the management
        # process indicating the ConsumerQueue was closed
        self.status = CLOSED
        self._manage_queue.put(ConsumerQueueCloseSignal())



class ProducerQueue(object):

    def __init__(self, _work_queue):
        self._work_queue = _work_queue
        self.status = OPEN


    # Delegate a bunch of functions to the underlying queue, but
    # always check first that `self` is open, raising
    # `ProducerQueueClosedException` if not
    def qsize(self, *args, **kwargs):
        self._raise_if_not_open('qsize')
        return self._work_queue.qsize(*args, **kwargs)
    def empty(self, *args, **kwargs):
        self._raise_if_not_open('empty')
        return self._work_queue.empty(*args, **kwargs)
    def full(self, *args, **kwargs):
        self._raise_if_not_open('full')
        return self._work_queue.full(*args, **kwargs)
    def put(self, *args, **kwargs):
        self._raise_if_not_open('put')
        return self._work_queue.put(*args, **kwargs)
    def put_nowait(self, *args, **kwargs):
        self._raise_if_not_open('put_nowait')
        return self._work_queue.put_nowait(*args, **kwargs)


    # Don't allow get and get_nowait to be called on ProducerQueues
    def get(self, *args, **kwargs):
        raise NotImplementedError('`ProducerQueue`s cannot `get()`.')
    def get_nowait(self, *args, **kwargs):
        raise NotImplementedError('`ProducerQueue`s cannot `get_nowait()`.')


    def _raise_if_not_open(self, method):
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
        self._work_queue.put(ProducerQueueCloseSignal())
