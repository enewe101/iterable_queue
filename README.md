# iterable\_queue
Prepare to feel relaxed.  Last time was the last time you will muck around 
with the unnecessarily messy logic of managing pools of producers and 
consumers in multiprocessing python programs.

## Install ##
`pip install iterable-queue`

## Why? ##

I don't know about you, but I'm sick of having to worry about managing the
details of multiprocessing in python.  For example, suppose you have a 
pool of *consumers* consuming tasks from a queue, which are being added
by some pool of *producers*.  Of course, you want the consumers to keep 
pulling work from the queue as long as that queue isn't empty.

The tricky part is, if the consumers are fast, they may continually drive
the queue to empty even though the producers are still adding work.  So 
in general, the producers also need to know if the consumers are all 
done.  This means using some kind of signalling, either within the 
queue itself or through some side channel.  Usually the producers need 
to know how many consumers are there, and vice versa, or else some 
centralized manager does.  And I'm just sick of that, I tell you.

I shouldn't need to put that kind of synchronization logic inside the 
actual code executed by the producers and consumers.  I say the *queue*
should keep track of that stuff, so I can stick to writing the actual logic 
of my program.

## Meet IterableQueue ##

IterableQueue is a directed queue, which means that it has 
(arbitrarily many) producer endpoints and consumer endpoints.  The 
IterableQueue knows how many producers and consumers are still open, and
this eliminates annoying worker coordination logic in the producer-consumer 
case.

Producers use the queue much like a `multiprocessing.Queue`, but with one
small variation: when they are done putting work on the queue, they call
`queue.close()`:

    producer_func(queue):
		while some_condition:
            ...
            queue.put(some_work)
            ...
        queue.close()

Consumers use the queue somewhat differently than `multiprocessing.Queue`,
and this is the beautiful part: consumers can treat the queue as an 
iterable, and iteration will automatically stop when there is no work left:

    consumer_func(queue):
        for work in queue:
            do_something_with(work)

Because the IterableQueue knows how many producers and consumers are open,
it knows when no more work will come through the queue, and so it can
stop iteration transparently.

## Use IterableQueue ##
The IterableQueue is a directed queue, meaning that it has producer and 
consumer endpoings.  Both wrap an underlying `multiprocessing.Queue`, and
expose *nearly* all of its methods.  An important exception is with the
`put()` and `get()` methods: you can only `put()` onto producer endpoints, 
and you can only `get()` from consumer endpoints.  This assumption is needed
for the management of consumer iteration to work automatically.

Let's setup a function that will be executed by *producers*, i.e. workers
that put onto the queue

    from random import random
    from time import sleep

    def producer_func(queue, producer_id):
        for i in range(10):
            sleep(random() / 100.0)
            queue.put(producer_id)
        queue.close()

Note that a producer should call `queue.close()` when it's done putting
stuff onto the queue.  This is different from `multiprocessing.Queue`, and 
this is what makes termination transparent from the perspective of the 
consumer (as we'll see in a moment).

Now let's setup a consumer function:

    def consumer_func(queue, consumer_id):
        for item in queue:
			sleep(random() / 100.0)
            print 'consumer %d saw item %d' % (consumer_id, item)

Notice how the consumer can treat the queue as an iterable.  This is 
because the queue knows when all of it's producers have closed, at which
point being empty means iteration should stop.  This means we don't need
to coordinate using side channels like a pipe or send termination signals
manually through the queue, and this means that the producers and consumers
don't need to be aware of one another.

Now, let's get some processes started.  First, we'll need an IterableQueue
Instance:

    from iterable_queue import IterableQueue
    iq = IterableQueue

And now, we just start an arbitrary number of producer and consumer 
processes.  We give *producers endpoints* to the producers, which we get
by calling `IterableQueue.get_producer()`, and we give *consumer endpoints*
to consumers by calling `IterableQueue.get_consumer()`:

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

Once we've finished making producer and consumer endpoints, we close
the iterable queue.  This let's the IterableQueue know that no new producers
will be coming onto the scene, so when the existing producers finish, 
there won't be any new work coming onto the queue

	# Once we've finished adding producers and consumers, we close the 
	# queue.
	iq.close()

And we're done.  Notice the lack of signalling and keeping track of manaing 
process completion, and the lack of `try ... except Empty` blocks.  You 
just iterate through the queue, and when its done its done.





