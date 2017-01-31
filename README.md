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
the queue to empty even though the producers are still busy adding work.  This 
means using some kind of signalling to keep track of whether producers are
still actively producing, either within the queue itself or through some side 
channel.  You also need to keep track of how many consumers there are, so that
the right number of "STOP" signals can be sent to the consumers.  This gets
tricky in the many to many case, and it just doesn't seem like one should have
to worry about it *in any case*.

The IterableQueue keeps track of all this stuff, taking care of signalling
transparently so that you can stick to writing the producer and consumer logic.

## Meet `IterableQueue` ##

`IterableQueue` is a directed queue, which means that it has 
(arbitrarily many) *producer endpoints* and *consumer endpoints*.  For
consumers, the IterableQueue can be treated like an iterable, meaning the
consumer will stop naturally without you having to do any signalling.  

And because the queue looks like an iterable, the consumer doesn't even have to
know it's consuming a queue.

Producers use the queue pretty much like a `multiprocessing.Queue`, but with one
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

The call to `queue.close()` is what makes it possible for the queue to know
when there's no more work comming, so that it can be treated like an iterable
by consumers:

```python
consumer_func(queue):
	for work in queue:
		do_something_with(work)
```

You can, if you choose, consume the queue "manually" by calling 
`queue.get()`.  `queue.Empty` being raised whenever the queue is empty, except
when the queue is empty, *and* all producers are finished, it raises
`iterable\_queue.Done`.

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
		queue.put(producer_id)
	queue.close()
```

Notice how the producer calls `queue.close()` when it's done putting
stuff onto the queue.

Now let's setup a consumer function:
```python
def consumer_func(queue, consumer_id):
	for item in queue:
		print('consumer %d saw item %d' % (consumer_id, item))
```

Notice how the consumer treats the queue as an iterable&mdash;there 
is no need to worry about detecting a termination condition.

Now, let's get some processes started.  First, we'll need an `IterableQueue`
Instance:

```python

from multiprocessing import Process
from iterable_queue import IterableQueue

# First we need an iterableQueue instance
iq = IterableQueue

# Now start a bunch of producers:
for producer_id in range(17):
	
	# Give each producer a "producer-queue"
	queue = iq.get_producer()
	Process(target=producer_func, args=(queue, producer_id)).start()

# And start a bunch of consumers
for consumer_id in range(13):

	# Give each consumer a "consumer-queue"
	queue = iq.get_consumer()
	Process(target=consumer_func, args=(queue, consumer_id)).start()

# And finally -- this is important!
iq.close()	# This let's the iterable queue no that no new producers endpoints will be made
```

Notice the last line&emdash;this let's the `IterableQueue` know that no new 
producers will be coming onto the scene and adding more work.

And we're done.  No signalling, no keeping track of process completion, 
and no `try ... except Empty`, just put on one end, and iterate on the other.

You can try the above example by running [`example.py`](https://github.com/enewe101/iterable_queue/blob/master/iterable_queue/example.py).





