=========================
Cinder Logging Guidelines
=========================

Purpose
~~~~~~~

This document provides practical logging guidelines for Cinder driver
maintainers and contributors, describing what to log, at which level, and what
to avoid.

It complements the :doc:`new_driver_checklist` and the `Oslo.log logging
guidelines <https://docs.openstack.org/oslo.log/latest/user/guidelines.html>`_.
All drivers must follow Oslo.log guidelines, with the rules here adding
Cinder-specific expectations.

Logging Goals
~~~~~~~~~~~~~

Logs should:

* Help operators diagnose production issues.
* Be grep-friendly and reference identifiable volumes, snapshots, and
  backends.
* Avoid leaking secrets or sensitive data.
* Avoid overwhelming clusters with excessive or noisy logs.
* Be consistent with logging behavior in other Cinder drivers.

What To Log
~~~~~~~~~~~

Use the following as a driver-focused checklist for choosing log levels.
Oslo.log remains the baseline.

INFO: Completed Work
--------------------

Use ``INFO`` for completed operations in past tense that operators care about.
Examples include:

* Volume created.
* Snapshot deleted.
* Driver initialized and ready.
* Non-secret startup information or capability summaries.

WARNING: Worth Tracking
-----------------------

Use ``WARNING`` for transient issues that did not fail the operation:

* Retries, fallbacks, or degraded behavior.
* Vendor messages that may affect stability but are not fatal.

ERROR: Action Required
----------------------

Use ``ERROR`` for definite failures where operator intervention may be
required. Include:

* What failed.
* Which resource was affected (volume, snapshot, group, attachment).
* Stable external identifiers such as backend volume name, LUN name, or export
  name.

Ensure logs can be correlated with backend logs.

DEBUG: Diagnostics
------------------

Use ``DEBUG`` for non-sensitive execution details required for debugging, such
as:

* RPC and driver-boundary tracing.
* Retry counts and polling operations.
* Start and end markers for long-running operations.
* REST call summaries:

  * HTTP method.
  * Resource type or path pattern.
  * HTTP status code.
  * Short error snippet on failure.

Drivers may use ``TraceWrapperMetaclass`` from
``cinder.volume.volume_utils`` to add method entry and exit markers at
``DEBUG`` level.

Formatting Guidelines
~~~~~~~~~~~~~~~~~~~~~

* Use lazy formatting for all log messages
  (for example, ``LOG.info('Volume %(id)s ...', {'id': vid})`` or equivalent
  lazy ``%s`` formatting).
* Prefer structured messages with named placeholders.
* Avoid pre-formatted strings or string interpolation before logging.

.. _logging_what_not_to_log:

What Not To Log
~~~~~~~~~~~~~~~

Secrets and Credentials
-----------------------

Never log:

* Passwords.
* API tokens or keys.
* CHAP or initiator secrets.
* iSCSI or Fibre Channel authentication tokens.
* Authentication or login payloads.

Sensitive or Overly Broad Context
---------------------------------

Avoid logging:

* Entire connector dictionaries.
* Vendor errors that may echo credentials or internal URLs, unless sanitized.

When ``DEBUG`` requires connector context, log only explicitly safe fields
such as host name, initiator IQN, or WWPN. Admins need these identifiers for
diagnosis, but logging the full connector dict risks exposing secrets or
internal paths.

Only log explicitly safe fields when ``DEBUG`` truly requires context.
Automatic masking of some keywords and sensitive information is handled by
oslo helper libraries (for example,
``oslo_utils.strutils.mask_dict_password``), but explicit care is still
required.

Wrong-Level Noise
-----------------

Avoid:

* Per-call ``INFO`` logs in hot paths.
* Periodic ``INFO`` logs inside tight loops.
* Narration-style ``INFO`` logs such as ``Entering create_volume``.

Use ``DEBUG`` instead for trace-style logging.

Huge Payloads
-------------

Avoid logging:

* Full JSON or XML bodies.
* Stack dumps at ``INFO`` or ``WARNING`` level.
* Multi-kilobyte messages.

At ``DEBUG`` level, truncate or summarize payloads unless a support case
explicitly requires full output.

Oslo.log Guidelines (Required Baseline)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Cinder drivers must follow Oslo.log conventions. Key expectations:

* ``INFO`` represents a completed unit of work in past tense.
* ``DEBUG`` is for developer-focused detail.
* ``WARNING`` indicates an issue worth tracking that may still succeed.
* ``ERROR`` signals failure or serious conditions requiring attention.
* ``AUDIT`` should not be used.
* Stack traces should be rare and typically logged only at ``ERROR`` for
  unexpected failures.

For details, see the `Oslo.log logging guidelines
<https://docs.openstack.org/oslo.log/latest/user/guidelines.html>`_.

Cinder Checklist Alignment
~~~~~~~~~~~~~~~~~~~~~~~~~~

Drivers must:

* Use appropriate log levels.
* Include volume, snapshot, or group identifiers in failure messages.
* Mark user-visible exception messages appropriately.

Identify The Object
-------------------

Logs should include operator-meaningful identifiers:

* Volume ID or name.
* Snapshot or group identifiers.
* Backend volume or LUN name.
* Export name or another stable external identifier.

On ``ERROR`` and ``WARNING``:

* Always tie the log message to the affected resource.
* Ensure logs can be correlated with commands such as ``cinder list`` or
  backend monitoring tools.
* Avoid confusing internal database identifiers unless they are part of the
  external contract.

Security and Privacy
--------------------

See :ref:`logging_what_not_to_log` above. In addition, drivers under review
must ensure failure messages never expose credentials and that vendor error
strings are sanitized before logging.

HTTP and REST APIs
------------------

At ``DEBUG`` level:

* Log HTTP method.
* Log resource or path pattern.
* Log HTTP status code.
* On failure, include a short response-body snippet.

Exceptions vs Logs
------------------

* Logs provide diagnostic context for operators.
* Exceptions communicate failure semantics to Cinder.
* Log at ``ERROR`` when raising or handling failures.
* Keep messages meaningful and actionable.

Use ``LOG.exception(...)`` inside an ``except`` block when a traceback helps
operators or support diagnose an unexpected failure. ``LOG.exception`` always
logs at ``ERROR`` level and includes exception info. See :doc:`i18n` for
translation markers on error-level messages.

Use ``LOG.error(...)`` when reporting a handled or expected failure where a
stack trace is not useful. Do not log the same failure at multiple levels
while re-raising; prefer one meaningful log at the handling boundary.

For patterns where logs and user-visible messages diverge, see
:doc:`user_messages`.

Example::

    LOG.exception("Failed to create volume.", resource=volume)

References
~~~~~~~~~~

* :doc:`new_driver_checklist`
* `Oslo.log Logging Guidelines
  <https://docs.openstack.org/oslo.log/latest/user/guidelines.html>`_
* `OpenStack Cinder Documentation
  <https://docs.openstack.org/cinder/latest/>`_
* `OpenStack Security logging guidelines
  <https://wiki.openstack.org/wiki/Security/Guidelines/logging_guidelines>`_
* `Nova Logging
  <https://docs.openstack.org/nova/latest/admin/manage-logs.html>`_
