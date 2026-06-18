.. _repo-overview:

=============
Repo Overview
=============

This document is a quick orientation to the Cinder repository layout.  It is a
map, not a substitute for the focused contributor documents linked from each
section.

Root files and directories
==========================

``HACKING.rst``
    Cinder coding style rules and Cinder-specific hacking check descriptions.

``AGENTS.md``
    Agent routing index and policy.

``.tmp/``
    Gitignored local scratch directory for notes, plans, and ephemeral output.

``tox.ini``
    Main local test, lint, docs, release-note, and generated-file command
    entry point.

``pyproject.toml``
    Build system and static package metadata managed with ``pbr``.

``.pre-commit-config.yaml``
    Linting hooks used by ``tox -e pep8``.

``requirements.txt`` / ``test-requirements.txt`` / ``doc/requirements.txt``
    Runtime, test, and documentation dependencies.  See :doc:`dependencies`.

``bindep.txt``
    Binary and operating-system package dependencies used by jobs.

``api-ref/``
    Block Storage API reference source.

``doc/``
    Cinder documentation source, including this contributor guide.

``releasenotes/``
    Reno release notes and release note documentation.

``tools/``
    Developer, validation, migration, and generated-file helper scripts.

``etc/``
    Example service configuration files and policy data.

``playbooks/``, ``roles/``
    Ansible content used by jobs and project automation.

Service code
============

``cinder/api/``
    REST API implementation, request validation, policy enforcement, and API
    microversion handling.  See :doc:`api_microversion_dev` for API contract
    changes.

``cinder/volume/``
    Volume service manager, TaskFlow flows, driver interface code, and storage
    backend drivers.  See :doc:`drivers` and :doc:`new_driver_checklist` before
    changing driver behavior.

``cinder/scheduler/``
    Scheduling service, backend selection logic, filters, and weighers.

``cinder/backup/``
    Backup service code and backup target drivers.

``cinder/db/``
    Database API and migrations.  See :doc:`database-migrations` and
    :doc:`rolling.upgrades` before changing schema, data migrations, or upgrade
    compatibility behavior.

``cinder/objects/``
    Versioned objects used for RPC and upgrade compatibility.  See
    :doc:`rolling.upgrades` before changing object versions or RPC payloads.

``cinder/policies/``
    Policy definitions for API authorization.

``cinder/cmd/``
    Console script entry points for Cinder services and management commands.

``cinder/common/``
    Shared helpers used across services.

Tests
=====

``cinder/tests/unit/``
    Unit tests.  The default tox test environment runs these tests through
    stestr.

``cinder/tests/functional/``
    Functional tests for broader in-repository workflows.

``cinder/tests/compliance/``
    Compliance tests for driver and API behavior.

``cinder/tests/hacking/``
    Cinder-specific hacking checks used by lint jobs.

See :doc:`testing` for test environment setup and invocation details.

Related contributor docs
========================

* :doc:`architecture` for service roles and high-level request flow.
* :doc:`rpc` for service communication concepts.
* :doc:`threading` for Cinder's eventlet and green-thread model.
* :doc:`attach_detach_conventions` and :doc:`attach_detach_conventions_v2` for
  attachment flows.
* :doc:`documentation` for documentation authoring and build commands.
* :doc:`releasenotes` for release note policy and formatting.
