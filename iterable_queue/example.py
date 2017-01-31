from __future__ import division
from __future__ import print_function
from builtins import range
from past.utils import old_div
from iterable_queue import IterableQueue
from multiprocessing import Process

NUM_PRODUCERS = 64
NUM_CONSUMERS = 64

def producer_func(queue, producer_id):
	for i in range(10):
		queue.put(producer_id)
	queue.close()


def consumer_func(queue, consumer_id):
	for item in queue:
		print('consumer %d saw item %d' % (consumer_id, item))


def run_example():
	iq = IterableQueue()

	consumers = []
	for consumer_id in range(NUM_CONSUMERS):
		queue = iq.get_consumer()
		p = Process(target=consumer_func, args=(queue, consumer_id))
		p.start()
		consumers.append(p)

	producers = []
	for producer_id in range(NUM_PRODUCERS):
		queue = iq.get_producer()
		p = Process(target=producer_func, args=(queue, producer_id))
		p.start()
		producers.append(p)

	iq.close()

	for p in producers + consumers:
		p.join()


if __name__ == '__main__':
	run_example()
