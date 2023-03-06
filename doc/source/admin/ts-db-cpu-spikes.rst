=====================================
Database CPU spikes during operations
=====================================

Query load upon the database can become a bottleneck that cascades across a
deployment and ultimately degrades not only the Cinder service but also the
whole OpenStack deployment.

Often, depending on load, query patterns, periodic tasks, and so on and so
forth, additional indexes may be needed to help provide hints to the database
so it can most efficently attempt to reduce the number of rows which need to
be examined in order to return a result set.

Adding indexes
--------------

In older releases, before 2023.1 (Antelope), there were some tables that
performed poorly in the presence of a large number of deleted resources
(volumes, snapshots, backups, etc) which resulted in high CPU loads on the DB
servers not only when listing those resources, but also when doing some
operations on them.  This was resolved by adding appropriate indexes to them.

This example below is specific to MariaDB/MySQL, but the syntax should be easy
to modify for operators using PostgreSQL, and it represents the changes that
older releases could add to resolve these DB server CPU spikes in such a way
that they would not conflict with the ones that Cinder introduced in 2023.1
(Antelope).

.. code-block:: sql

   use cinder;
   create index groups_deleted_project_id_idx on groups (deleted, project_id);
   create index group_snapshots_deleted_project_id_idx on groups (deleted, project_id);
   create index volumes_deleted_project_id_idx on volumes (deleted, project_id);
   create index volumes_deleted_host_idx on volumes (deleted, host);
   create index snapshots_deleted_project_id_idx on snapshots (deleted, project_id);
   create index backups_deleted_project_id_idx on backups (deleted, project_id);
