from iterable_queue import IterableQueue
from multiprocessing import Process
from random import random
from time import sleep

NUM_PRODUCERS = 17
NUM_CONSUMERS = 13

def producer_func(queue, producer_id):
	for i in range(10):
		sleep(random() / 100.0)
		queue.put(producer_id)
	queue.close()

def consumer_func(queue, consumer_id):
	for item in queue:
		sleep(random() / 100.0)
		print 'consumer %d saw item %d' % (consumer_id, item)

iq = IterableQueue()

for producer_id in range(17):
	queue = iq.get_producer()
	Process(target=producer_func, args=(queue, producer_id)).start()

for consumer_id in range(13):
	queue = iq.get_consumer()
	Process(target=consumer_func, args=(queue, consumer_id)).start()

iq.close()

