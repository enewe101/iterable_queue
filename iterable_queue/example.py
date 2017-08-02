from __future__ import division
from __future__ import print_function
from builtins import range
from past.utils import old_div
from iterable_queue import IterableQueue
from multiprocessing import Process

NUM_PRODUCERS = 3
NUM_CONSUMERS = 5

def producer_func(queue, producer_id):
    for i in range(10):
        queue.put(producer_id)
    queue.close()


def consumer_func(queue, consumer_id):
    for item in queue:
        print('consumer %d saw item %d' % (consumer_id, item))


def run_example():
    # Make an iterableQueue instance
    iq = IterableQueue()

    # Start a bunch of producers, give each one a producer endpoint
    producers = []
    for producer_id in range(NUM_PRODUCERS):
        queue = iq.get_producer()
        p = Process(target=producer_func, args=(queue, producer_id))
        p.start()
        producers.append(p)

    # And start a bunch of consumers
    consumers = []
    for consumer_id in range(NUM_CONSUMERS):

        # Give each consumer a "consumer-queue"
        consumer_endpoint = iq.get_consumer()
        p = Process(target=consumer_func, args=(consumer_endpoint, consumer_id))
        p.start()
        consumers.append(p)

    # Lastly, *this is important*, close the IterableQueue.
    iq.close()    # This indicates no new producers endpoints will be made

    # Wait for workers to finish
    for p in producers + consumers:
        p.join()


if __name__ == '__main__':
    run_example()
