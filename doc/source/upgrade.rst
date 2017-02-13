Upgrades
========

Cinder aims to provide upgrades with minimal downtime.

This should be achieved for both data and control plane. As Cinder doesn't
interfere with data plane, its upgrade shouldn't affect any volumes being
accessed by virtual machines.

Keeping the control plane running during an upgrade is more difficult. This
document's goal is to provide preliminaries and a detailed procedure of such
upgrade.

Concepts
--------

Here are the key concepts you need to know before reading the section on the
upgrade process:

RPC version pinning
'''''''''''''''''''

Through careful RPC versioning, newer services are able to talk to older
services (and vice-versa). The versions are autodetected using information
reported in ``services`` table. In case of receiving ``CappedVersionUnknown``
or ``ServiceTooOld`` exceptions on service start, you're probably having some
old orphaned records in that table.

Graceful service shutdown
'''''''''''''''''''''''''

Many cinder services are python processes listening for messages on a AMQP
queue. When the operator sends SIGTERM signal to the process, it stops getting
new work from its queue, completes any outstanding work and then terminates.
During this process, messages can be left on the queue for when the python
process starts back up. This gives us a way to shutdown a service using older
code, and start up a service using newer code with minimal impact.

.. note::
  Waiting for completion of long-running operations (e.g. slow volume copy
  operation) may take a while.

.. note::
  This was tested with RabbitMQ messaging backend and may vary with other
  backends.

Online Data Migrations
''''''''''''''''''''''

To make DB schema migrations less painful to execute, since Liberty, all data
migrations are banned from schema migration scripts. Instead, the migrations
should be done by background process in a manner that doesn't interrupt running
services (you can also execute online data migrations with services turned off
if you're doing a cold upgrade). In Ocata a new ``cinder-manage db
online-data-migrations`` utility was added for that purpose.  Before upgrading
Ocata to Pike, you need to run this tool in the background, until it tells you
no more migrations are needed.  Note that you won't be able to apply Pike's
schema migrations before completing Ocata's online data migrations.

API load balancer draining
''''''''''''''''''''''''''

When upgrading API nodes, you can make your load balancer only send new
connections to the newer API nodes, allowing for a seamless update of your API
nodes.

DB prune deleted rows
'''''''''''''''''''''

Currently resources are soft deleted in the database, so users are able to
track instances in the DB that are created and destroyed in production.
However, most people have a data retention policy, of say 30 days or 90 days
after which they will want to delete those entries. Not deleting those entries
affects DB performance as indices grow very large and data migrations take
longer as there is more data to migrate. To make pruning easier there's a
``cinder-manage db purge <age_in_days>`` command that permanently deletes
records older than specified age.

Versioned object backports
''''''''''''''''''''''''''

RPC pinning ensures new services can talk to the older service's method
signatures. But many of the parameters are objects that may well be too new for
the old service to understand. Cinder makes sure to backport an object to a
version that it is pinned to before sending.

Minimal Downtime Upgrade Procedure
----------------------------------

Plan your upgrade
'''''''''''''''''

* Read and ensure you understand the release notes for the next release.

* Make a backup of your database. Cinder does not support downgrading of the
  database. Hence, in case of upgrade failure, restoring database from backup
  is the only choice.

* Note that there's an assumption that live upgrade can be performed only
  between subsequent releases. This means that you cannot upgrade Liberty
  directly into Newton, you need to upgrade to Mitaka first.

* To avoid dependency hell it is advised to have your Cinder services deployed
  separately in containers or Python venvs.

* Note that Cinder is basing version detection on what is reported in the
  ``services`` table in the DB. Before upgrade make sure you don't have any
  orphaned old records there, because these can block starting newer services.
  You can clean them up using ``cinder-manage service remove <binary> <host>``
  command.

* Assumed service upgrade order is cinder-api, cinder-scheduler, cinder-volume
  and finally cinder-backup.

Rolling upgrade process
'''''''''''''''''''''''

To reduce downtime, the services can be upgraded in a rolling fashion. It means
upgrading a few services at a time. To minimise downtime you need to have HA
Cinder deployment, so at the moment a service is upgraded, you'll keep other
service instances running.

Before maintenance window
"""""""""""""""""""""""""

* First you should execute required DB schema migrations. To achieve that
  without interrupting your existing installation, install new Cinder code in
  new venv or a container and run the DB sync (``cinder-manage db sync``).
  These schema change operations should have minimal or no effect on
  performance, and should not cause any operations to fail.

* At this point, new columns and tables may exist in the database. These
  DB schema changes are done in a way that both the N and N+1 release can
  perform operations against the same schema.

During maintenance window
"""""""""""""""""""""""""

1. cinder-api services should go first. In HA deployment you're typically
   running them behind a load balancer (e.g. HAProxy), so you need to take one
   service instance out of the balancer, shut it down, upgrade the code and
   dependencies, and start the service again. Then you can plug it back into
   the load balancer. Cinder's internal mechanisms will make sure that new
   c-api will detect that it's running with older versions and will downgrade
   any communication.

   .. note::

     You may want to start another instance of older c-api to handle the load
     while you're upgrading your original services.

2. Then you should repeat first step for all of the cinder-api services.

3. Next service is cinder-scheduler. It is load-balanced by the message queue,
   so the only thing you need to worry about is to shut it down gracefully
   (using ``SIGTERM`` signal) to make sure it will finish all the requests
   being processed before shutting down. Then you should upgrade the code and
   restart the service.

4. Repeat third step for all of your cinder-scheduler services.

5. Then you proceed to upgrade cinder-volume services. The problem here is that
   due to Active/Passive character of this service, you're unable to run
   multiple instances of cinder-volume managing a single volume backend. This
   means that there will be a moment when you won't have any cinder-volume in
   your deployment and you want that disruption to be as short as possible.

   .. note::

     The downtime here is non-disruptive as long as it doesn't exceed the
     service heartbeat timeout. If you don't exceed that, then
     cinder-schedulers will not notice that cinder-volume is gone and the
     message queue will take care of queuing any RPC messages until
     cinder-volume is back.

     To make sure it's achieved, you can either lengthen the timeout by
     tweaking ``service_down_time`` value in ``cinder.conf``, or prepare
     upgraded cinder-volume on another node and do a very quick switch by
     shutting down older service and starting the new one just after that.

     Also note that in case of A/P HA configuration you need to make sure both
     primary and secondary c-vol have the same hostname set (you can override
     it using ``host`` option in ``cinder.conf``), so both will be listening on
     the same message queue and will accept the same messages.

6. Repeat fifth step for all cinder-volume services.

7. Now we should proceed with (optional) cinder-backup services. You should
   upgrade them in the same manner like cinder-scheduler.

   .. note::

     Backup operations are time consuming, so shutting down a c-bak service
     without interrupting ongoing requests can take time. It may be useful to
     disable the service first using ``cinder service-disable`` command, so it
     won't accept new requests, and wait a reasonable amount of time until all
     the in-progress jobs are completed. Then you can proceed with the upgrade.
     To make sure the backup service finished all the ongoing requests, you can
     check the service logs.

   .. note::

     Until Liberty cinder-backup was tightly coupled with cinder-volume service
     and needed to coexist on the same physical node. This is not true starting
     with Mitaka version. If you're still keeping that coupling, then your
     upgrade strategy for cinder-backup should be more similar to how
     cinder-volume is upgraded.

After maintenance window
""""""""""""""""""""""""

* Once all services are running the new code, double check in the DB that
  there are no old orphaned records in ``services`` table (Cinder doesn't
  remove the records when service is gone or service hostname is changed, so
  you need to take care of that manually; you should be able to distinguish
  dead records by looking at when the record was updated). Cinder is basing its
  RPC version detection on that, so stale records can prevent you from going
  forward.

* Now all services are upgraded, we need to send the ``SIGHUP`` signal, so
  all the services clear any cached service version data. When a new service
  starts, it automatically detects which version of the service's RPC protocol
  to use, and will downgrade any communication to that version. Be advised
  that cinder-api service doesn't handle ``SIGHUP`` so it needs to be
  restarted. It's best to restart your cinder-api services as last ones, as
  that way you make sure API will fail fast when user requests new features on
  a deployment that's not fully upgraded (new features can fail when RPC
  messages are backported to lowest common denominator). Order of the rest of
  the services shouldn't matter.

* Now all the services are upgraded, the system is able to use the latest
  version of the RPC protocol and able to access all the features of the new
  release.

* At this point, you must also ensure you update the configuration, to stop
  using any deprecated features or options, and perform any required work
  to transition to alternative features. All the deprecated options should
  be supported for one cycle, but should be removed before your next
  upgrade is performed.

* Since Ocata, you also need to run ``cinder-manage db online-data-migrations``
  command to make sure data migrations are applied. The tool let's you limit
  the impact of the data migrations by using ``--max_number`` option to limit
  number of migrations executed in one run. You need to complete all of the
  migrations before starting upgrade to the next version (e.g. you need to
  complete Ocata's data migrations before proceeding with upgrade to Pike; you
  won't be able to execute Pike's DB schema migrations before completing
  Ocata's data migrations).
