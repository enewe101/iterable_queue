# iterable\_queue
Prepare to feel relaxed.  Last time was the last time you will muck around 
with the unnecessarily messy logic of managing pools of producers and 
consumers in multiprocessing python programs.

## Install ##

```bash
pip install iterable-queue
```

## Why? ##

I don't know about you, but I'm sick of having to worry about managing the
details of multiprocessing in python.  For example, suppose you have a 
pool of *consumers* consuming tasks from a queue, which is being populated
by a pool of *producers*.  Of course, you want the consumers to keep 
pulling work from the queue as long as that queue isn't empty.

The tricky part is, if the consumers are fast, they may continually drive
the queue to empty even though the producers are still busy adding work.  So 
in general, the producers also need to know if the consumers are all 
done.  This means using some kind of signalling, either within the 
queue itself or through some side channel.  It also means keeping track, 
somewhere,
of how many producers are still working, and when all producers are 
finished, notifying each consumer of that fact.
This means that, right inside the
producer and consumer code, you need to embed this signalling and tracking
logic, which is complicated and just feels wrong.  
*And I'm just sick of it, I tell you.*

Here's what I say: let the *queue* keep track of that stuff, so I can 
stick to writing the logic of production and consumption for
my producers and consumers.

## Meet `IterableQueue` ##

`IterableQueue` is a directed queue, which means that it has 
(arbitrarily many) *producer endpoints* and *consumer endpoints*.  This
directedness enables `IterableQueue` to know how many producers and 
consumers are still at work, and this lets it take care of the tracking
and signalling necessary to tell the difference between being 
temporarily empty, and being empty with no new work coming.  Because the
`IterableQueue` knows when no new work is coming, it can be treated like
an iterable on the consumer end, stopping iteration naturally when all work 
is complete.

Producers use the queue much like a `multiprocessing.Queue`, but with one
small variation: when they are done putting work on the queue, they call
`queue.close()`:

```python
producer_func(queue):
	while some_condition:
		...
		queue.put(some_work)
		...
	queue.close()
```

The beautiful part is in how consumers use the queue, which is somewhat
differently than it is with `multiprocessing.Queue`: 
consumers can simply treat the queue as an iterable:

```python
consumer_func(queue):
	for work in queue:
		do_something_with(work)
```

Because the `IterableQueue` knows how many producers and consumers are open,
it knows when no more work will come through the queue, and so it can
stop iteration transparently.

(Although you can, if you choose, consume the queue "manually" by calling 
`queue.get()`, with `Queue.Empty` being raised whenever the queue is empty, and `iterable_queue.ConsumerQueueClosedException` being raised when the queue is empty with no more work coming.)

## Use `IterableQueue` ##
As mentioned, `IterableQueue` is a directed queue, meaning that it has 
producer and consumer endpoints.  Both wrap the same underlying 
`multiprocessing.Queue`, and expose *nearly* all of its methods.
Important exceptions are the `put()` and `get()` methods: you can only
`put()` onto producer endpoints, and you can only `get()` from consumer 
endpoints.  This distinction is needed for the management of consumer 
iteration to work automatically.

To see an example, let's setup a function that will be executed by 
*producers*, i.e. workers that *put onto* the queue:

```python
from random import random
from time import sleep

def producer_func(queue, producer_id):
	for i in range(10):
		sleep(random() / 100.0)
		queue.put(producer_id)
	queue.close()
```

Notice how the producer calls `queue.close()` when it's done putting
stuff onto the queue.

Now let's setup a consumer function:
```python
def consumer_func(queue, consumer_id):
	for item in queue:
		sleep(random() / 100.0)
		print 'consumer %d saw item %d' % (consumer_id, item)
```

Notice again how the consumer treats the queue as an iterable&mdash;there 
is no need to worry about detecting a termination condition.

Now, let's get some processes started.  First, we'll need an `IterableQueue`
Instance:

```python
from iterable_queue import IterableQueue
iq = IterableQueue
```

Now, we just start an arbitrary number of producer and consumer 
processes.  We give *producer endpoints* to the producers, which we get
by calling `IterableQueue.get_producer()`, and we give *consumer endpoints*
to consumers by calling `IterableQueue.get_consumer()`:

```python
from multiprocessing import Process

# Start a bunch of producers:
for producer_id in range(17):
	
	# Give each producer a "producer-queue"
	queue = iq.get_producer()
	Process(target=producer_func, args=(queue, producer_id)).start()

# Start a bunch of consumers
for consumer_id in range(13):

	# Give each consumer a "consumer-queue"
	queue = iq.get_consumer()
	Process(target=consumer_func, args=(queue, consumer_id)).start()
```

Finally&mdash;and this is important&mdash;once we've finished making 
producer and consumer endpoints, we close the `IterableQueue`:  

```python
iq.close()
```

This let's the `IterableQueue` know that no new producers will be coming 
onto the scene and adding more work.

And we're done.  Notice the pleasant lack of signalling and keeping track 
of process completion, and notice the lack of `try ... except Empty` 
blocks: you just iterate through the queue, and when its done its done.

You can try the above example by running [`example.py`](https://github.com/enewe101/iterable_queue/blob/master/iterable_queue/example.py).





