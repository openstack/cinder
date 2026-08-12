Threading model
===============

.. warning::
   **This document is out of date and requires revision.**  Beginning around
   the Flamingo release, OpenStack has begun transitioning away from
   eventlet in favor of adding support for running services with native
   threading.

   Cinder is basically following the `Nova strategy
   <https://docs.openstack.org/nova/latest/reference/threading.html#native-threading>`_
   of using ``futurist.ThreadPoolExecutors`` to run concurrent tasks while
   the ``oslo.service`` and ``oslo.messaging`` libraries can be configured
   to use native threads to execute their tasks.

   References:

   * `Mailing list discussion
     <https://lists.openstack.org/archives/list/openstack-discuss@lists.openstack.org/thread/YO5CZDVAJ6QSF734ALWSGNOQDDAIOXKI/?sort=date>`_
     (started November 2023)
   * `Eventlet removal community goal
     <https://governance.openstack.org/tc/goals/selected/remove-eventlet.html>`_
     (merged July 2024)

All OpenStack services use *green thread* model of threading, implemented
through using the Python `eventlet <http://eventlet.net/>`_ and
`greenlet <http://greenlet.readthedocs.io/en/latest/>`_ libraries.

Green threads use a cooperative model of threading: thread context
switches can only occur when specific eventlet or greenlet library calls are
made (e.g., sleep, certain I/O calls). From the operating system's point of
view, each OpenStack service runs in a single thread.

The use of green threads reduces the likelihood of race conditions, but does
not completely eliminate them. In some cases, you may need to use the
``@utils.synchronized(...)`` decorator to avoid races.

In addition, since there is only one operating system thread, a call that
blocks that main thread will block the entire process.

Yielding the thread in long-running tasks
-----------------------------------------
If a code path takes a long time to execute and does not contain any methods
that trigger an eventlet context switch, the long-running thread will block
any pending threads.

This scenario can be avoided by adding a call to
``cinder.utils.cooperative_yield()`` in the long-running code path. In eventlet
mode this triggers a context switch by calling ``time.sleep(0)``; in native
threading mode it is a no-op because real OS threads yield preemptively::

    from cinder import utils
    ...
    utils.cooperative_yield()

Do not call ``time.sleep(0)`` or ``eventlet.sleep(0)`` directly — the C339
hacking check will flag it.  Use ``cooperative_yield()`` so that the yield is
automatically skipped when running with native threads.

MySQL access and eventlet
-------------------------
There are some MySQL DB API drivers for oslo.db, like `PyMySQL`_, MySQL-python
etc. PyMySQL is the default MySQL DB API driver for oslo.db, and it works well
with eventlet. MySQL-python uses an external C library for accessing the MySQL
database. Since eventlet cannot use monkey-patching to intercept blocking calls
in a C library, queries to the MySQL database using libraries like MySQL-python
will block the main thread of a service.

The Diablo release contained a thread-pooling implementation that did not
block, but this implementation resulted in a `bug`_ and was removed.

See this `mailing list thread`_ for a discussion of this issue, including
a discussion of the `impact on performance`_.

.. _bug: https://bugs.launchpad.net/cinder/+bug/838581
.. _mailing list thread: https://lists.launchpad.net/openstack/msg08118.html
.. _impact on performance: https://lists.launchpad.net/openstack/msg08217.html
.. _PyMySQL: https://wiki.openstack.org/wiki/PyMySQL_evaluation
