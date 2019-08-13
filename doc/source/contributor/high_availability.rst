High Availability
=================

In this guide we'll go over design and programming considerations related to
high availability in Cinder.

The document aims to provide a single point of truth in all matters related to
Cinder's high availability.

Cinder developers must always have these aspects present during the design and
programming of the Cinder core code, as well as the drivers' code.

Most topics will focus on Active-Active deployments.  Some topics covering node
and process concurrency will also apply to Active-Passive deployments.


Overview
--------

There are 4 services that must be considered when looking at a highly available
Cinder deployment: API, Scheduler, Volume, Backup.

Each of these services has its own challenges and mechanisms to support
concurrent and multi node code execution.

This document provides a general overview of Cinder aspects related to high
availability, together with implementation details.  Given the breadth and
depth required to properly explain them all, it will fall short in some places.
It will provide external references to expand on some of the topics hoping to
help better understand them.

Some of the topics that will be covered are:

- Job distribution.
- Message queues.
- Threading model.
- Versioned Objects used for rolling upgrades.
- Heartbeat system.
- Mechanism used to clean up out of service cluster nodes.
- Mutual exclusion mechanisms used in Cinder.

It's good to keep in mind that Cinder threading model is based on eventlet's
green threads.  Some Cinder and driver code may use native threads to prevent
thread blocking, but that's not the general rule.

Throughout the document we'll be referring to clustered and non clustered
Volume services.  This distinction is not based on the number of services
running, but on their configurations.

A non clustered Volume service is one that will be deployed as Active-Passive
and has not been included in a Cinder cluster.

On the other hand, a clustered Volume service is one that can be deployed as
Active-Active because it is part of a Cinder cluster.  We consider a Volume
service to be clustered even when there is only one node in the cluster.


Job distribution
----------------

Cinder uses RPC calls to pass jobs to Scheduler, Volume, and Backup services.
A message broker is used for the transport layer on the RPC calls and
parameters.

Job distribution is handled by the message broker using message queues.  The
different services, except the API, listen on specific message queues for RPC
calls.

Based on the maximum number of nodes that will connect, we can differentiate
two types of message queues: those with a single listener and those with
multiple listeners.

We use single listener queues to send RPC calls to a specific service in a
node. For example, when the API calls a non clustered Volume service to create
a snapshot.

Message queues having multiple listeners are used in operations such as:

- Creating any volume.  Call made from the API to the Scheduler.
- Creating a volume in a clustered Volume service.  Call made from the
  Scheduler to the Volume service.
- Attaching a volume in a clustered Volume service.  Call made from the API to
  the Volume service.

Regardless of the number of listeners, all the above mentioned RPC calls are
unicast calls.  The caller will place the request in a queue in the message
broker and a single node will retrieve it and execute the call.

There are other kinds of RPC calls, those where we broadcast a single RPC call
to multiple nodes.  The best example of this type of call is the Volume service
capabilities report sent to all the Schedulers.

Message queues are fair queues and are used to distribute jobs in a round robin
fashion.  Single target RPC calls made to message queues with multiple
listeners are distributed in round robin.  So sending three request to a
cluster of 3 Schedulers will send one request to each one.

Distribution is content and workload agnostic.  A node could be receiving all
the quick and easy jobs while another one gets all the heavy lifting and its
ongoing workload keeps increasing.

Cinder's job distribution mechanism allows fine grained control over who to
send RPC calls.  Even on clustered Volume services we can still access
individual nodes within the cluster.  So developers must pay attention to where
they want to send RPC calls and ask themselves: Is the target a clustered
service?  Is the RPC call intended for *any* node running the service?  Is it
for a *specific* node?  For *all* nodes?

The code in charge of deciding the target message queue, therefore the
recipient, is in the `rpcapi.py` files.  Each service has its own file with the
RPC calls: `volume/rpcapi.py`, `scheduler/rpcapi.py`, and `backup/rpcapi.py`.

For RPC calls the different `rcpapi.py` files ultimately use the `_get_cctxt`
method from the `cinder.rpc.RPCAPI` class.

For a detailed description on the issue, ramifications, and solutions, please
refer to the `Cinder Volume Job Distribution`_.

The `RabbitMQ tutorials`_ are a good way to understand message brokers general
topics.


Heartbeats
----------

Cinder services, with the exception of API services, have a periodic heartbeat
to indicate they are up and running.

When services are having health issues, they may decide to stop reporting
heartbeats, even if they are running.  This happens during initialization if
the driver cannot be setup correctly.

The database is used to report service heartbeats.  Fields `report_count` and
`updated_at`, in the `services` table, keep a heartbeat counter and the last
time the counter was updated.

There will be multiple database entries for Cinder Volume services running
multiple backends.  One per backend.

Using a date-time to mark the moment of the last heartbeat makes the system
time relevant for Cinder's operation.  A significant difference in system times
on our nodes could cause issues in a Cinder deployment.

All services report and expect the `updated_at` field to be UTC.

To determine if a service is up, we check the time of the last heartbeat to
confirm that it's not older than `service_down_time` seconds.  Default value
for `service_down_time` configuration option is 60 seconds.

Cinder uses method `is_up`, from the `Service` and `Cluster` Versioned Object,
to ensure consistency in the calculations across the whole code base.

Heartbeat frequency in Cinder services is determined by the `report_interval`
configuration option.  The default is 10 seconds, allowing network and database
interruptions.

Cinder protects itself against some incorrect configurations.  If
`report_interval` is greater or equal than `service_down_time`, Cinder will log
a warning and use a service down time of two and a half times the configured
`report_interval`.

.. note:: It is of utter importance having the same `service_down_time` and
   `report_interval` configuration options in all your nodes.

In each service's section we'll expand this topic with specific information
only relevant to that service.


Cleanup
-------

Power outages, hardware failures, unintended reboots, and software errors.
These are all events that could make a Cinder service unexpectedly halt its
execution.

A running Cinder service is usually carrying out actions on resources.  So when
the service dies unexpectedly, it will abruptly stop those operations.  Stopped
operations in this way leaves resources in transitioning states.  For example a
volume could be left in a `deleting` or `creating` status.  If left alone
resources will remain in this state forever, as the service in charge of
transitioning them to a rest status (`available`, `error`, `deleted`) is no
longer running.

Existing reset-status operations allow operators to forcefully change the state
of a resource.  But these state resets are not recommended except in very
specific cases and when we really know what we are doing.

Cleanup mechanisms are tasked with service's recovery after an abrupt stop of
the service.  They are the recommended way to resolve stuck transitioning
states caused by sudden service stop.

There are multiple cleanup mechanisms in Cinder, but in essence they all follow
the same logic.  Based on the resource type and its status the mechanism
determines the best cleanup action that will transition the state to a rest
state.

Some actions require a resource going through several services.  In this case
deciding the cleanup action may also require taking into account where the
resource was being processed.

Cinder has two types of cleanup mechanisms:

- On node startup: Happen on Scheduler, Volume, and Backup services.
- Upon user request.  User requested cleanups can only be triggered on
  Scheduler and Volume nodes.

When a node starts it will do a cleanup, but only for the resources that were
left in a transitioning state when the service stopped.  It will never touch
resources from other services in the cluster.

Node startup cleanup is slightly different on services supporting user
requested cleanups -Scheduler and Volume- than on Backup services.  Backup
cleanups will be covered in the service's section.

For services supporting user requested cleanups we can differentiate the
following tasks:

- Tracking transitioning resources: Using workers table and Cleanable Versioned
  Objects methods.
- Defining when a resource must be cleaned if service dies: Done in Cleanable
  Versioned Objects.
- Defining how a resource must be cleaned: Done in the service manager.

.. note:: All Volume services can accept cleanup requests, doesn't matter if
   they are clustered or not.  This will provide a better alternative to the
   reset-state mechanism to handle resources stuck in a transitioning state.


Workers table
~~~~~~~~~~~~~

For Cinder Volume managed resources -Volumes and Snapshots- we used to
establish a one-to-one relationship between a resource and the volume service
managing it.  A resource would belong to a node if the resource's `host` field
matched that of the running Cinder Volume service.

Snapshots must always be managed by the same service as the volume they
originate from, so they don't have a `host` field in the database.  In this
case the parent volume's `host` is used to determine who owns the resource.

Cinder-Volume services can be clustered, so we no longer have a one-to-one
owner relationship.  On clustered services we use the `cluster_name` database
field instead of the `host` to determine ownership.  Now we have a one-to-many
ownership relationship.

When a clustered service abruptly stops running, any of the nodes from the same
cluster can cleanup the resources it was working on.  There is no longer a need
to restart the service to get the resources cleaned by the node startup cleanup
process.

We keep track of the resources our Cinder services are working on in the
`workers` table.  Only resources that can be cleaned are tracked.  This table
stores the resource type and id, the status that should be cleared on service
failure, the service that is working on it, etc.  And we'll be updating this
table as the resources move from service to service.

`Worker` entries are not passed as RPC parameters, so we don't need a Versioned
Object class to represent them.  We only have the `Worker` ORM class to
represent database entries.

Following subsections will cover implementation details required to develop new
cleanup resources and states. For a detailed description on the issue,
ramifications, and overall solution, please refer to the `Cleanup spec`_.

Tracking resources
~~~~~~~~~~~~~~~~~~

Resources supporting cleanup using the workers table must inherit from the
`CinderCleanableObject` Versioned Object class.

This class provides helper methods and the general interface used by Cinder for
the cleanup mechanism.  This interface is conceptually split in three tasks:

- Manage workers table on the database.
- Defining what states must be cleaned.
- Defining how to clean resources.

Among methods provided by the `CinderCleanableObject` class the most important
ones are:

- `is_cleanable`: Checks if the resource, given its current status, is
  cleanable.
- `create_worker`: Create a worker entry on the API service.
- `set_worker`: Create or update worker entry.
- `unset_worker`: Remove an entry from the database.  This is a real delete,
  not a soft-delete.
- `set_workers`: Function decorator to create or update worker entries.

Inheriting classes must define `_is_cleanable` method to define which resource
states can be cleaned up.

Earlier we mentioned how cleanup depends on a resource's current state.  But it
also depends under what version the services are running.  With rolling updates
we can have a service running under an earlier pinned version for compatibility
purposes.  A version X service could have a resource that it would consider
cleanable, but it's pinned to version X-1, where it was not considered
cleanable.  To avoid breaking things, the resource should be considered as non
cleanable until the service version is unpinned.

Implementation of `_is_cleanable` method must take them both into account.  The
state, and the version.

Volume's implementation is a good example, as workers table was not supported
before version 1.6:

.. code-block:: python

   @staticmethod
   def _is_cleanable(status, obj_version):
       if obj_version and obj_version < 1.6:
           return False
       return status in ('creating', 'deleting', 'uploading', 'downloading')

Tracking states in the workers table starts by calling the `create_worker`
method on the API node.  This is best done on the different `rpcapi.py` files.

For example, a create volume operation will go from the API service to the
Scheduler service, so we'll add it in `cinder/scheduler/rpcapi.py`:

.. code-block:: python

   def create_volume(self, ctxt, volume, snapshot_id=None, image_id=None,
                     request_spec=None, filter_properties=None,
                     backup_id=None):
       volume.create_worker()

But if we are deleting a volume or creating a snapshot the API will call the
Volume service directly, so changes should go in `cinder/scheduler/rpcapi.py`:

.. code-block:: python

   def delete_volume(self, ctxt, volume, unmanage_only=False, cascade=False):
       volume.create_worker()

Once we receive the call on the other side's manager we have to call the
`set_worker` method.  To facilitate this task we have the `set_workers`
decorator that will automatically call `set_worker` for any cleanable versioned
object that is in a cleanable state.

For the create volume on the Scheduler service:

.. code-block:: python

   @objects.Volume.set_workers
   @append_operation_type()
   def create_volume(self, context, volume, snapshot_id=None, image_id=None,
                     request_spec=None, filter_properties=None,
                     backup_id=None):

And then again for the create volume on the Volume service:

.. code-block:: python

   @objects.Volume.set_workers
   def create_volume(self, context, volume, request_spec=None,
                     filter_properties=None, allow_reschedule=True):

In these examples we are using the `set_workers` method from the `Volume`
Versioned Object class.  But we could be using it from any other class as it is
a `staticmethod` that is not overwritten by any of the classes.

Using the `set_workers` decorator will cover most of our use cases, but
sometimes we may have to call the `set_worker` method ourselves.  That's the
case when transitioning from `creating` state to `downloading`.  The `worker`
database entry was created with the `creating` state and the working service
was updated when the Volume service received the RPC call.  But once we change
the status to `creating` the worker and the resource status don't match, so the
cleanup mechanism will ignore the resource.

To solve this we add another worker update in the `save` method from the
`Volume` Versioned Object class:

.. code-block:: python

   def save(self):

       ...

       if updates.get('status') == 'downloading':
           self.set_worker()

Actions on resource cleanup
~~~~~~~~~~~~~~~~~~~~~~~~~~~

We've seen how to track cleanable resources in the `workers` table.  Now we'll
cover how to define the actions used to cleanup a resource.

Services using the `workers` table inherit from the `CleanableManager` class
and must implement the `_do_cleanup` method.

This method receives a versioned object to clean and indicates whether we
should keep the `workers` table entry.  On asynchronous cleanup tasks method
must return `True` and take care of removing the worker entry on completion.

Simplified version of the cleanup of the Volume service, illustrating
synchronous and asynchronous cleanups and how we can do a synchronous cleanup
and take care ourselves of the `workers` entry:

.. code-block:: python

    def _do_cleanup(self, ctxt, vo_resource):
        if isinstance(vo_resource, objects.Volume):
            if vo_resource.status == 'downloading':
                self.driver.clear_download(ctxt, vo_resource)

            elif vo_resource.status == 'deleting':
                if CONF.volume_service_inithost_offload:
                    self._add_to_threadpool(self.delete_volume, ctxt,
                                            vo_resource, cascade=True)
                else:
                    self.delete_volume(ctxt, vo_resource, cascade=True)
                return True

        if vo_resource.status in ('creating', 'downloading'):
            vo_resource.status = 'error'
            vo_resource.save()

When the volume is `downloading` we don't return anything, so the caller
receives `None`, which evaluates to not keep the row entry.  When the status is
`deleting` we call `delete_volume` synchronously or asynchronously.  The
`delete_volume` has the `set_workers` decorator, that calls `unset_worker` once
the decorated method has successfully finished.  So when calling
`delete_volume` we must ask the caller of `_do_cleanup` to not try to remove
the `workers` entry.

Cleaning resources
~~~~~~~~~~~~~~~~~~

We may not have a `Worker` Versioned Object because we didn't need it, but we
have a `CleanupRequest` Versioned Object to specify resources for cleanup.

Resources will be cleaned when a node starts up and on user request.  In both
cases we'll use the `CleanupRequest` that contains a filtering of what needs to
be cleaned up.

The `CleanupRequest` can be considered as a filter on the `workers` table to
determine what needs to be cleaned.

Managers for services using the `workers` table must support the startup
cleanup mechanism.  Support for this mechanism is provided via the `init_host`
method in the `CleanableManager` class.  So managers inheriting from
`CleanableManager` must make sure they call this `init_host` method.  This can
be done using `CleanableManager` as the first inherited class and using `super`
to call the parent's `init_host` method, or by calling the class method
directly: `cleanableManager.init_host(self, ...)`.

`CleanableManager`'s `init_host` method will create a `CleanupRequest` for the
current service before calling its `do_cleanup` method with it before
returning.  Thus cleaning up all transitioning resources from the service.

For user requested cleanups, the API generates a `CleanupRequest` object using
the request's parameters and calls the scheduler's `work_cleanup` RPC with
it.

The Scheduler receives the `work_cleanup` RPC call and uses the
`CleanupRequest` to filter services that match the request.  With this list of
services the Scheduler sends an individual cleanup request for each of the
services.  This way we can spread the cleanup work if we have multiple services
to cleanup.

The Scheduler checks the service to clean to know where it must send the clean
request.  Scheduler service cleanup can be performed by any Scheduler, so we
send it to the scheduler queue where all Schedulers are listening.  In the
worst case it will come back to us if there is no other Scheduler running at
the time.

For the Volume service we'll be sending it to the cluster message queue if it's
a clustered service, or to a single node if it's non clustered.  But unlike
with the Scheduler, we can't be sure that there is a service to do the cleanup,
so we check if the service or cluster is up before sending the request.

After sending all the cleanup requests, the Scheduler will return a list of
services that have received a cleanup request, and all the services that didn't
because they were down.


Mutual exclusion
----------------

In Cinder, as many other concurrent and parallel systems, there are "critical
sections".  Code sections that share a common resource that can only be
accessed by one of them at a time.

Resources can be anything, not only Cinder resources such as Volumes and
Snapshots, and they can be local or remote.  Examples of resources are
libraries, command line tools, storage target groups, etc.

Exclusion scopes can be per process, per node, or global.

We have four mutual exclusion mechanisms available during Cinder development:

- Database locking using resource states.
- Process locks.
- Node locks.
- Global locks.

For performance reasons we must always try to avoid using any mutual exclusion
mechanism.  If avoiding them is not possible, we should try to use the
narrowest scope possible and reduce the critical section as much as possible.
Locks by decreasing order of preference are: process locks, node locks, global
locks, database locks.

Status based locking
~~~~~~~~~~~~~~~~~~~~

Many Cinder operations are inherently exclusive and the Cinder core code
ensures that drivers will not receive contradictory or incompatible calls.  For
example, you cannot clone a volume if it's being created.  And you shouldn't
delete the source volume of an ongoing snapshot.

To prevent these from happening Cinder API services use resource status fields
to check for incompatibilities preventing operations from getting through.

There are exceptions to this rule, for example the force delete operation that
ignores the status of a resource.

We should also be aware that administrators can forcefully change the status of
a resource and then call the API, bypassing the check that prevents multiple
operations from being requested to the drivers.

Resource locking using states is expanded upon in the `Race prevention`_
subsection in the `Cinder-API`_ section.

Process locks
~~~~~~~~~~~~~

Cinder services are multi-threaded -not really since we use greenthreads-, so
the narrowest possible scope of locking is among the threads of a single
process.

Some cases where we may want to use this type of locking are when we share
arrays or dictionaries between the different threads within the process, and
when we use a Python or C library that doesn't properly handle concurrency and
we have to be careful with how we call its methods.

To use this locking in Cinder we must use the `synchronized` method in
`cinder.utils`.  This method in turn uses the `synchronized` method from
`oslo_concurrency.lockutils` with the `cinder-` prefix for all the locks to
avoid conflict with other OpenStack services.

The only required parameter for this usage is the name of the lock.  The name
parameter provided for these locks must be a literal string value.  There is no
kind of templating support.

Example from `cinder/volume/throttling.py`:

.. code-block:: python

   @utils.synchronized('BlkioCgroup')
   def _inc_device(self, srcdev, dstdev):

.. note:: When developing a driver, and considering which type of lock to use,
   we must remember that Cinder is a multi backend service.  So the same driver
   can be running multiple times on different processes in the same node.

Node locks
~~~~~~~~~~

Sometimes we want to define the whole node as the scope of the lock.  Our
critical section requires that only one thread in the whole node is using the
resource.  This inter process lock ensures that no matter how many processes
and backends want to access the same resource, only one will access it at a
time.  All others will have to wait.

These locks are useful when:

- We want to ensure there's only one ongoing call to a command line program.
  That's the case of the `cinder-rtstool` command in
  `cinder/volume/targets/lio.py`, and the `nvmetcli` command in
  `cinder/volume/targets/nvmet.py`.

- Common initialization in all processes in the node.  This is the case of the
  backup service cleanup code.  The backup service can run multiple processes
  simultaneously for the same backend, but only one of them can run the cleanup
  code on start.

- Drivers not supporting Active-Active configurations.  Any operation that
  should only be performed by one driver at a time.  For example creating
  target groups for a node.

This type of lock use the same method as the `Process locks`_, `synchronized`
method from `cinder.utils`. Here we need to pass two parameters, the name of
the lock, and `external=True` to make sure that file locks are being used.

The name parameter provided for these locks must be a literal string value.
There is no kind of templating support.

Example from `cinder/volume/targest/lio.py`:

.. code-block:: python

   @staticmethod
   @utils.synchronized('lioadm', external=True)
   def _execute(*args, **kwargs):


Example from `cinder/backup/manager.py`:

.. code-block:: python

   @utils.synchronized('backup-pgid-%s' % os.getpgrp(),
                       external=True, delay=0.1)
   def _cleanup_incomplete_backup_operations(self, ctxt):

.. warning:: These are not fair locks.  Order in which the lock is acquired by
   callers may differ from request order.  Starvation is possible, so don't
   choose a generic lock name for all your locks and try to create a unique
   name for each locking domain.

Global locks
~~~~~~~~~~~~

Global locks, also known as distributed locks in Cinder, provide mutual
exclusion in the global scope of the Cinder services.

They allow you to have a lock regardless of the backend, for example to prevent
deleting a volume that is being cloned, or making sure that your driver is only
creating a Target group at a time, in the whole Cinder deployment, to avoid
race conditions.

Global locking functionality is provided by the `synchronized` decorator from
`cinder.coordination`.

This method is more advanced than the one used for the `Process locks`_ and the
`Node locks`_, as the name supports templates.  For the template we have all
the method parameters as well as `f_name` that represents that name of the
method being decorated.  Templates must use Python's `Format Specification
Mini-Language`_.

Using brackets we can access the function name `'{f_name}'`, an attribute of a
parameter `'{volume.id}'`, a key in a dictonary `{snapshot['name']}`, etc.

Up to date information on the method can be found in the `synchronized method's
documentation`_.

Example from the delete volume operation in `cinder/volume/manager.py`.  We
use the `id` attribute of the `volume` parameter, and the function name to form
the lock name:

.. code-block:: python

   @coordination.synchronized('{volume.id}-{f_name}')
   @objects.Volume.set_workers
   def delete_volume(self, context, volume, unmanage_only=False,
                     cascade=False):

Example from create snapshot in `cinder/volume/drivers/nfs.py`, where we use an
attribute from `self`, and a recursive reference in the `snapshot` parameter.

.. code-block:: python

   @coordination.synchronized('{self.driver_prefix}-{snapshot.volume.id}')
   def create_snapshot(self, snapshot):

Internally Cinder uses the `Tooz library`_ to provide the distributed locking.
By default, this library is configured for Active-Passive deployments, where it
uses file locks equivalent to those used for `Node locks`_.

To support Active-Active deployments a specific driver will need to be
configured using the `backend_url` configuration option in the `coordination`
section.

For a detailed description of the requirement for global locks in cinder please
refer to the `replacing local locks with Tooz`_ and `manager local locks`_
specs.


Cinder locking
~~~~~~~~~~~~~~

Cinder uses the different locking mechanisms covered in this section to assure
mutual exclusion on some actions.  Here's an *incomplete* list:

Barbican keys
  - Lock scope: Global.
  - Critical section: Migrate Barbican encryption keys.
  - Lock name: `{id}-_migrate_encryption_key`.
  - Where: `_migrate_encryption_key` method.
  - File: `cinder/keymgr/migration.py`.

Backup service
  - Lock scope: Node.
  - Critical section: Cleaning up resources at startup.
  - Lock name: `backup-pgid-{process-group-id}`.
  - Where: `_cleanup_incomplete_backup_operations` method.
  - File: `cinder/backup/manager.py`.

Image cache
  - Lock scope: Global.
  - Critical section: Create a new image cache entry.
  - Lock name: `{image_id}`.
  - Where: `_prepare_image_cache_entry` method.
  - File: `cinder/volume/flows/manager/create_volume.py`.

Throttling:
  - Lock scope: Process.
  - Critical section: Set parameters of a cgroup using `cgset` CLI.
  - Lock name: `''BlkioCgroup'`.
  - Where: `_inc_device` and `_dec_device` methods.
  - File: `cinder/volume/throttling.py`.

Volume deletion:
  - Lock scope: Global.
  - Critical section: Volume deletion operation.
  - Lock name: `{volume.id}-delete_volume`.
  - Where: `delete_volume` method.
  - File: `cinder/volume/manager.py`.

Volume deletion request:
  - Lock scope: Status based.
  - Critical section: Volume delete RPC call.
  - Status requirements: attach_status != 'attached' && not migrating
  - Where: `delete` method.
  - File: `cinder/volume/api.py`.

Snapshot deletion:
  - Lock scope: Global.
  - Critical section: Snapshot deletion operation.
  - Lock name: `{snapshot.id}-delete_snapshot`.
  - Where: `delete_snapshot` method.
  - File: `cinder/volume/manager.py`.

Volume creation:
  - Lock scope: Global.
  - Critical section: Protect source of volume creation from deletion.  Volume
    or Snapshot.
  - Lock name: `{snapshot-id}-delete_snapshot` or
    `{volume-id}-delete_volume}`.
  - Where: Inside `create_volume` method as context manager for calling
    `_fun_flow`.
  - File: `cinder/volume/manager.py`.

Attach volume:
  - Lock scope: Global.
  - Critical section: Updating DB to show volume is attached.
  - Lock name: `{volume_id}`.
  - Where: `attach_volume` method.
  - File: `cinder/volume/manager.py`.

Detach volume:
  - Lock scope: Global.
  - Critical section: Updating DB to show volume is detached.
  - Lock name: `{volume_id}-detach_volume`.
  - Where: `detach_volume` method.
  - File: `cinder/volume/manager.py`.

Volume upload image:
  - Lock scope: Status based.
  - Critical section: `copy_volume_to_image` RPC call.
  - Status requirements: status = 'available' or (force && status = 'in-use')
  - Where: `copy_volume_to_image` method.
  - File: `cinder/volume/api.py`.

Volume extend:
  - Lock scope: Status based.
  - Critical section: `extend_volume` RPC call.
  - Status requirements: status in ('in-use', 'available')
  - Where: `_extend` method.
  - File: `cinder/volume/api.py`.

Volume migration:
  - Lock scope: Status based.
  - Critical section: `migrate_volume` RPC call.
  - Status requirements: status in ('in-use', 'available') && not migrating
  - Where: `migrate_volume` method.
  - File: `cinder/volume/api.py`.

Volume retype:
  - Lock scope: Status based.
  - Critical section: `retype` RPC call.
  - Status requirements: status in ('in-use', 'available') && not migrating
  - Where: `retype` method.
  - File: `cinder/volume/api.py`.


Driver locking
~~~~~~~~~~~~~~

There is no general rule on where drivers should use locks.  Each driver has
its own requirements and limitations determined by the storage backend and the
tools and mechanisms used to manage it.

Even if they are all different, commonalities may exist between drivers.
Providing a list of where some drivers are using locks, even if the list is
incomplete, may prove useful to other developers.

To contain the length of this document and keep it readable, the list with the
:doc:`drivers_locking_examples` has its own document.


Cinder-API
----------

The API service is the public face of Cinder.  Its REST API makes it possible
for anyone to manage and consume block storage resources.  So requests from
clients can, and usually do, come from multiple sources.

Each Cinder API service by default will run multiple workers.  Each worker is
run in a separate subprocess and will run a predefined maximum number of green
threads.

The number of API workers is defined by the `osapi_volume_workers`
configuration option.  Defaults to the number of CPUs available.

Number of green threads per worker is defined by the `wsgi_default_pool_size`
configuration option.  Defaults to 100 green threads.

The service takes care of validating request parameters.  Any detected error is
reported immediately to the user.

Once the request has been validated, the database is changed to reflect the
request.  This can result in adding a new entry to the database and/or
modifying an existing entry.

For create volume and create snapshot operations the API service will create a
new database entry for the new resource. And the new information for the
resource will be returned to the caller right after the service passes the
request to the next Cinder service via RPC.

Operations like retype and delete will change the database entry referenced by
the request, before making the RPC call to the next Cinder service.

Create backup and restore backup are two of the operations that will create a
new entry in the database, and modify an existing one.

These database changes are very relevant to the high availability operation.
Cinder core code uses resource states extensively to control exclusive access
to resources.

Race prevention
~~~~~~~~~~~~~~~

The API service checks that resources referenced in requests are in a valid
state.  Unlike allowed resource states, valid states are those that allow an
operation to proceed.

Validation usually requires checking multiple conditions.  Careless coding
leaves Cinder open to race conditions.  Patterns in the form of DB data read,
data check, and database entry modification, must be avoided in the Cinder API
service.

Cinder has implemented a custom mechanism, called conditional updates, to
prevent race conditions.  Leverages the SQLAlchemy ORM library to abstract the
equivalent ``UPDATE ...  FROM ... WHERE;`` SQL query.

Complete reference information on the conditional updates mechanism is
available on the :doc:`api_conditional_updates` development document.

For a detailed description on the issue, ramifications, and solution, please
refer to the `API Race removal spec`_.


Cinder-Volume
-------------

The most common deployment option for Cinder-Volume is as Active-Passive.  This
requires a common storage backend, the same Cinder backend configuration in all
nodes, having the `backend_host` set on the backend sections, and using a
high-availability cluster resource manager like Pacemaker.

.. attention::  Having the same `host` value configured on more than one Cinder
   node is highly discouraged.  Using `backend_host` in the backend section is
   the recommended way to set Active-Passive configurations.  Setting the same
   `host` field will make Scheduler and Backup services report using the same
   database entry in the `services` table.  This may create a good number of
   issues: We cannot tell when the service in a node is down, backups services
   will break other running services operation on start, etc.

For Active-Active configurations we need to include the Volume services that
will be managing the same backends on the cluster.  To include a node in a
cluster, we need to define its name in the `[DEFAULT]` section using the
`cluster` configuration option, and start or restart the service.

.. note:: We can create a cluster with a single volume node.  Having a single
   node cluster allows us to later on add new nodes to the cluster without
   restarting the existing node.

.. warning:: The name of the cluster must be unique and cannot match any of the
   `host` or `backend_host` values.  Non unique values will generate duplicated
   names for message queues.

When a Volume service is configured to be part of a cluster, and the service is
restarted, the manager detects the change in configuration and moves existing
resources to the cluster.

Resources are added to the cluster in the `_include_resources_in_cluster`
method setting the `cluster_name` field in the database.  Volumes, groups,
consistency groups, and image cache elements are added to the cluster.

Clustered Volume services are different than normal services.  To determine if
a backend is up, it is no longer enough checking `service.is_up`, as that will
only give us the status of a specific service.  In a clustered deployment there
could be other services that are able to service the same backend.  That's why
we'll have to check if a service is clustered using `cinder.is_clustered` and
if it is, check the cluster's `is_up` property instead:
`service.cluster.is_up`.

In the code, to detect if a cluster is up, the `is_up` property from the
`Cluster` Versioned Object uses the `last_heartbeat` field from the same
object.  The `last_heartbeat` is a *column property* from the SQLAlchemy ORM
model resulting from getting the latest `updated_at` field from all the
services in the same cluster.

RPC calls
~~~~~~~~~

When we discussed the `Job distribution`_ we mentioned message queues having
multiple listeners and how they were used to distribute jobs in a round robin
fashion to multiple nodes.

For clustered Volume services we have the same queues used for broadcasting and
to address a specific node, but we also have queues to broadcast to the cluster
and to send jobs to the cluster.

Volume services will be listening in all these queues and they can receive
request from any of them.  Which they'll have to do to process RPC calls
addressed to the cluster or to themselves.

Deciding the target message queue for request to the Volume service is done in
the `volume/rpcapi.py` file.

We use method `_get_cctxt`, from the `VolumeAPI` class, to prepare the client
context to make RPC calls.  This method accepts a `host` parameter to indicate
where we want to make the RPC.  This `host` parameter refers to both hosts and
clusters, and is used to determine the server and the topic.

When calling the `_get_cctx` method, we would need to pass the resource's
`host` field if it's not clustered, and `cluster_name` if it is.  To facilitate
this, clustered resources implement the `service_topic_queue` property that
automatically gives you the right value to pass to `_get_cctx`.

An example for the create volume:

.. code-block:: python

   def create_volume(self, ctxt, volume, request_spec, filter_properties,
                     allow_reschedule=True):
       cctxt = self._get_cctxt(volume.service_topic_queue)
       cctxt.cast(ctxt, 'create_volume',
                  request_spec=request_spec,
                  filter_properties=filter_properties,
                  allow_reschedule=allow_reschedule,
                  volume=volume)

As we know, snapshots don't have a `host` or `cluseter_name` fields, but we can
still use the `service_topic_queue` property from the `Snapshot` Versioned
Object to get the right value.  The `Snapshot` internally checks these values
from the `Volume` Versioned Object linked to that `Snapshot` to determine the
right value.  Here's an example for deleting a snapshot:

.. code-block:: python

   def delete_snapshot(self, ctxt, snapshot, unmanage_only=False):
       cctxt = self._get_cctxt(snapshot.service_topic_queue)
       cctxt.cast(ctxt, 'delete_snapshot', snapshot=snapshot,
                  unmanage_only=unmanage_only)

Replication
~~~~~~~~~~~

Replication v2.1 failover is requested on a per node basis, so when a
failover request is received by the API it is then redirected to a specific
Volume service.  Only one of the services that form the cluster for the storage
backend will receive the request, and the others will be oblivious to this
change and will continue using the same replication site they had been using
before.

To support the replication feature on clustered Volume services, drivers need
to implement the `Active-Active replication spec`_.  In this spec the
`failover_host` method is split in two, `failover` and `failover_completed`.

On a backend supporting replication on Active-Active deployments,
`failover_host` would end up being a call to `failover` followed by a call to
`failover_completed`.

Code extract from the RBD driver:

.. code-block:: python

   def failover_host(self, context, volumes, secondary_id=None, groups=None):
       active_backend_id, volume_update_list, group_update_list = (
           self.failover(context, volumes, secondary_id, groups))
       self.failover_completed(context, secondary_id)
       return active_backend_id, volume_update_list, group_update_list

Enabling Active-Active on Drivers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Supporting Active-Active configurations is driver dependent, so they have to
opt in.  By default drivers are not expected to support Active-Active
configurations and will fail on startup if we try to deploy them as such.

Drivers can indicate they support Active-Active setting the class attribute
`SUPPORTS_ACTIVE_ACTIVE` to `True`.  If a single driver supports multiple
storage solutions, it can leave the class attribute as it is, and set it as an
overriding instance attribute on `__init__`.

There is no well defined procedure required to allow driver maintainers to set
`SUPPORTS_ACTIVE_ACTIVE` to `True`.  Though there is an ongoing effort to write
a spec on `testing Active-Active`_.

So for now, we could say that it's "self-certification".  Vendors must do their
own testing until they are satisfied with their testing.

Real testing of Active-Active deployments requires multiple Cinder Volume nodes
on different hosts, as well as a properly configured Tooz DLM.

Driver maintainers can use Devstack to catch the rough edges on their initial
testing.  Running 2 Cinder Volume services on an All-In-One DevStack
installation makes it easy to deploy and debug.

Running 2 Cinder Volume services on the same node simulating different nodes
can be easily done:

- Creating a new directory for local locks:  Since we are running both services
  on the same node, a file lock could make us believe that the code would work
  on different nodes.  Having a different lock directory, default is
  `/opt/stack/data/cinder`, will prevent this.
- Creating a layover cinder configuration file:  Cinder supports having
  different configurations files where each new files overrides the common
  parts of the old ones.  We can use the same base cinder configuration
  provided by DevStack and write a different file with a `[DEFAULT]` section
  that configures `host` (to anything different than the one used in the first
  service), and `lock_path` (to the new directory we created).  For example we
  could create `/etc/cinder/cinder2.conf`.
- Create a new service unit:  This service unit should be identical to the
  existing `devstack@c-vol` except replace the `ExecStart` that should have the
  postfix `--config-file /etc/cinder/cinder2.conf`.

Once we have tested it in DevStack way we should deploy Cinder in a new Node,
and continue with the testings.

It is not necessary to do the DevStack step first, we can jump to having Cinder
in multiple nodes right from the start.

Whatever way we decide to test this, we'll have to change `cinder.conf` and add
the `cluster` configuration option and restart the Cinder service.  We also
need to modify the driver under test to include the
`SUPPORTS_ACTIVE_ACTIVE = True` class attribute.


Cinder-Scheduler
----------------

Unlike the Volume service, the Cinder Scheduler has supported Active-Active
deployments for a long time.

Unfortunately, current support is not perfect, scheduling on Active-Active
deployments has some issues.

The root cause of these issues is that the scheduler services don't have a
reliable single source of truth for the information they rely on to make the
scheduling.

Volume nodes periodically send a broadcast with the backend stats to all the
schedulers.  The stats include total storage space, free space, configured
maximum over provisioning, etc.  All the backends' information is stored in
memory at the Schedulers, and used to decide where to create new volumes,
migrate them on a retype, and so on.

For additional information on the stats, please refer to the
:ref:`volume stats <drivers_volume_stats>`
section of the Contributor/Developer docs.

Trying to keep updated stats, schedulers reduce available free space on
backends in their internal dictionary.  These updates are not shared between
schedulers, so there is not a single source of truth, and other schedulers
don't operate with the same information.

Until the next stat reports is sent, schedulers will not get in sync.  This may
create unexpected behavior on scheduling.

There are ongoing efforts to fix this problem.  Multiple solutions are being
discussed: using the database as a single source of truth, or using an external
placement service.

When we added Active-Active support to the Cinder Volume service we had to
update the scheduler to understand it.  This mostly entailed 3 things:

- Setting the `cluster_name` field on Versioned Objects once a backend has been
  chosen.

- Grouping stats for all clustered hosts.  We don't want to have individual
  entries for the stats of each host that manages a cluster, as there should be
  only one up to date value.  We stopped using the `host` field as the id for
  each host, and created a new property called `backend_id` that takes into
  account if the service is clustered and returns the host or the cluster as
  the identifier.

- Prevent race conditions on stats reports.  Due to the concurrency on the
  multiple Volume services in a cluster, and the threading in the Schedulers,
  we could receive stat reports out of order (more up to date stats last).  To
  prevent this we started time stamping the stats on the Volume services.
  Using the timestamps schedulers can discard older stats.

Heartbeats
~~~~~~~~~~

Like any other non API service, schedulers also send heartbeats using the
database.

The difference is that, unlike other services, the purpose of these heartbeats
is merely informative.  Admins can easily know whether schedulers are running
or not with a Cinder command.

Using the same `host` configuration in all nodes defeats the whole purpose of
reporting heartbeats in the schedulers, as they will all report on the same
database entry.


Cinder-Backups
--------------

Originally, the Backup service was not only limited to Active-Passive
deployments, but it was also tightly coupled to the Volume service.  This
coupling meant that the Backup service could only backup volumes created by the
Volume service running on the same node.

In the Mitaka cycle, the `Scalable Backup Service spec`_ was implemented.  This
added support for Active-Active deployments to the backup service.

The Active-Active implementation for the backup service is different than the
one we explained for the Volume Service.  The reason lays not only on the
fact that the Backup service supported it first, but also on it not supporting
multiple backends, and not using the Scheduler for any operations.

Scheduling
~~~~~~~~~~

For backups, it's the API the one selecting the host that will do the backup,
using methods `_get_available_backup_service_host`,
`_is_backup_service_enabled`, and `_get_any_available_backup_service`.

These methods use the Backup services' heartbeats to determine which hosts are
up to handle requests.

Cleaning
~~~~~~~~

Cleanup on Backup services is only performed on start up.

To know what resources each node is working on, they set the `host` field in
the backup Versioned Object when they receive the RPC call.  That way they can
select them for cleanup on start.

The method in charge of doing the cleanup for the backups is called
`_cleanup_incomplete_backup_operations`.

Unlike with the Volume service we cannot have a backup node clean up after
another node's.


.. _API Race removal spec: https://specs.openstack.org/openstack/cinder-specs/specs/mitaka/cinder-volume-active-active-support.html
.. _Cinder Volume Job Distribution: https://specs.openstack.org/openstack/cinder-specs/specs/ocata/ha-aa-job-distribution.html
.. _RabbitMQ tutorials: https://www.rabbitmq.com/getstarted.html
.. _Cleanup spec: https://specs.openstack.org/openstack/cinder-specs/specs/newton/ha-aa-cleanup.html
.. _synchronized method's documentation: https://docs.openstack.org/cinder/latest/contributor/api/cinder.coordination.html#module-cinder.coordination
.. _Format Specification Mini-Language: https://docs.python.org/2.7/library/string.html#formatspec
.. _Tooz library: https://opendev.org/openstack/tooz
.. _replacing local locks with Tooz: https://specs.openstack.org/openstack/cinder-specs/specs/mitaka/ha-aa-tooz-locks.html
.. _manager local locks: https://specs.openstack.org/openstack/cinder-specs/specs/newton/ha-aa-manager_locks.html
.. _Active-Active replication spec: https://specs.openstack.org/openstack/cinder-specs/specs/ocata/ha-aa-replication.html
.. _testing Active-Active: https://review.openstack.org/#/c/443504
.. _Scalable Backup Service spec: https://specs.openstack.org/openstack/cinder-specs/specs/mitaka/scalable-backup-service.html
