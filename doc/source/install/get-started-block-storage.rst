=====================================
Cinder Block Storage service overview
=====================================

The OpenStack Block Storage service (Cinder) adds persistent storage
to a virtual machine. Block Storage provides an infrastructure for managing
volumes, and interacts with OpenStack Compute to provide volumes for
instances. The service also enables management of volume snapshots, and
volume types.

The Block Storage service consists of the following components:

cinder-api
  Accepts API requests, and routes them to the ``cinder-volume`` for
  action.

cinder-volume
  Interacts directly with the Block Storage service, and processes
  such as the ``cinder-scheduler``. It also interacts with these processes
  through a message queue. The ``cinder-volume`` service responds to read
  and write requests sent to the Block Storage service to maintain
  state. It can interact with a variety of storage providers through a
  driver architecture.

cinder-scheduler daemon
  Selects the optimal storage provider node on which to create the
  volume. A similar component to the ``nova-scheduler``.

cinder-backup daemon
  The ``cinder-backup`` service provides backing up volumes of any type to
  a backup storage provider. Like the ``cinder-volume`` service, it can
  interact with a variety of storage providers through a driver
  architecture.

Messaging queue
  Routes information between the Block Storage processes.
