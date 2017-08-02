# iterable-queue
Prepare to feel relaxed.  Last time was the last time you will muck around 
with the unnecessarily messy logic of managing pools of producers and 
consumers in multiprocessing python programs.

## Install ##

```bash
pip install iterable-queue
```

## Why? ##

Suppose you have a pool of *consumers* consuming tasks from a queue, which is
being populated by a pool of *producers*.  Of course, you want the consumers to
keep pulling work from the queue as long as that queue isn't empty.

The tricky part is, if the consumers are fast, they may continually drive
the queue to empty even though the producers are still busy adding work.  So,
how do the consumers know if the work is really done, or if the queue is just
temporarily empty?

If you have one producer and many consumers, or if you have one consumer and
many producers, you can manage it by sending special `done` signals over the
queue.  I find even that to be a bit annoying, but when you have many producers
and many consumers, things get more complex.

## Meet `IterableQueue` ##

`IterableQueue` handles signalling in the background to keep track of how many
producers and consumers are active, so you only have to worry about doing the
actual producing and consuming.  The queue itself knows the difference between
being temporarily empty, and being *done*.

`IterableQueue` is a directed queue, which means that it has 
(arbitrarily many) *producer endpoints* and *consumer endpoints*.  

Because it knows when it's done, it can support the iterable interface.  That
means that for consumers, the queue looks just like an iterable.  The consumers
don't even have to know they have a queue.  

Producers use the queue pretty much like a `multiprocessing.Queue`, but with 
one small variation: when they are done putting work on the queue, they should 
call `queue.close()`:

```python
producer_func(queue):
    while some_condition:
        ...
        queue.put(some_work)
        ...
    queue.close()
```

The call to `IterableQueue.close()` is what makes it possible for the queue to 
know when there's no more work coming, so that it can be treated like an
iterable by consumers:

```python
consumer_func(queue):
    for work in queue:
        do_something_with(work)
```

You can, if you choose, consume the queue "manually" by calling `queue.get()`.
It delegates to an underlying `multiprocessing.Queue` and supports all of the
usual arguments.  Calling `get()` on a queue, with `block=True` and
`timeout=None` (the defaults) will raise `Queue.Empty` if the queue is empty,
like usual.  However, if the queue is not just empty, but properly *done* (i.e.
there are no more active producers) `IterableQueue.Done` will be raised
instead.

## Example ##
As mentioned, `IterableQueue` is a directed queue, meaning that it has 
producer and consumer endpoints.  Both wrap the same underlying 
`multiprocessing.Queue`, and expose *nearly* all of its methods.
Important exceptions are the `put()` and `get()` methods: you can only
`put()` onto producer endpoints, and you can only `get()` from consumer 
endpoints.  This distinction is needed for the management of consumer 
iteration to work automatically.

Let's start by setting up a function that will be executed by *producers*, i.e.
workers that *put onto* the queue:

```python
def producer_func(queue, producer_id):
    for i in range(10):
        queue.put(producer_id)
    queue.close()
```

Notice how the producer calls `queue.close()` when it's done putting
stuff onto the queue.

Now let's set up a consumer function:
```python
def consumer_func(queue, consumer_id):
    for item in queue:
        print('consumer %d saw item %d' % (consumer_id, item))
```

Notice how the consumer treats the queue as an iterable.

Now, let's get some processes started:

```python

from multiprocessing import Process
from iterable_queue import IterableQueue

NUM_PRODUCERS = 3
NUM_CONSUMERS = 5

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

# Lastly -- this is important -- close the IterableQueue.
iq.close()    # This indicates no new producers endpoints will be made

# Wait for workers to finish
for p in producers + consumers:
    p.join()

```

Notice the last line&mdash;this lets the `IterableQueue` know that no new 
producers will be coming onto the scene and adding more work.

And we're done.  No signalling, no keeping track of process completion, 
and no `try ... except Empty`, just put on one end, and iterate on the other.

The output you'd see from running the example is below.  You can try the above example by running [`example.py`](https://github.com/enewe101/iterable_queue/blob/master/iterable_queue/example.py).

```
consumer 1 saw item 0
consumer 0 saw item 0
consumer 1 saw item 0
consumer 0 saw item 0
consumer 1 saw item 0
consumer 1 saw item 0
consumer 0 saw item 1
consumer 1 saw item 1
consumer 2 saw item 0
consumer 0 saw item 0
consumer 2 saw item 1
consumer 0 saw item 0
consumer 1 saw item 2
consumer 0 saw item 1
consumer 2 saw item 2
consumer 1 saw item 2
consumer 0 saw item 1
consumer 1 saw item 2
consumer 3 saw item 0
consumer 2 saw item 1
consumer 1 saw item 2
consumer 2 saw item 1
consumer 3 saw item 2
consumer 3 saw item 1
consumer 0 saw item 2
consumer 1 saw item 2
consumer 2 saw item 1
consumer 4 saw item 1
consumer 2 saw item 2
consumer 4 saw item 2
```





