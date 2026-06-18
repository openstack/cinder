.. _dependencies:

============
Dependencies
============

Cinder uses the standard OpenStack dependency management model.  Keep
dependency changes in the file that matches how the dependency is used so that
local development, packaging, and CI jobs install the same inputs.

Python dependencies
===================

Runtime Python dependencies belong in ``requirements.txt``.  These are
packages needed when Cinder services or libraries run.

Test-only Python dependencies belong in ``test-requirements.txt``.  These are
packages needed to run Cinder tests and local developer tooling but not by a
deployed Cinder service.

Documentation-only Python dependencies belong in ``doc/requirements.txt``.
These are packages needed to build or validate the documentation, such as
Sphinx extensions, documentation themes, release note tooling, and redirect
test tools.

Driver dependencies
===================

Optional storage, backup, or target driver dependencies must be handled so that
operators, packagers, and CI jobs can discover them.  Do not add an optional
backend dependency to the base runtime dependency set unless it is required for
all Cinder deployments.

Cinder defines per-driver optional dependency groups in the
``[project.optional-dependencies]`` table of ``pyproject.toml``.  When a new
driver requires a Python package that is not needed by all deployments, add it
as a driver-specific optional dependency group rather than to
``requirements.txt``.

When a driver needs operating-system packages, list them in ``bindep.txt`` with
an appropriate profile instead of documenting a manual setup step.  New driver
work should also follow :doc:`new_driver_checklist`.

System packages
===============

Binary and operating-system package dependencies belong in ``bindep.txt``.
Use bindep profiles such as ``test`` or ``doc`` when a package is only needed
by a specific class of jobs.

Packaging metadata
==================

Cinder uses ``pbr`` for Python packaging metadata.  Do not introduce
alternative version or dependency management systems such as
``setuptools-scm``.  Keep package dependencies in the requirement files above
so OpenStack constraints and CI can manage them consistently.

``pyproject.toml`` records static package metadata per `PEP 621`_, such as the
project name, classifiers, and entry points.  The version and main Python
dependency list are dynamic and managed by ``pbr``; they are not edited in the
``dependencies`` table.

Runtime, test, and documentation Python dependencies must continue to be
declared in ``requirements.txt``, ``test-requirements.txt``, and
``doc/requirements.txt`` as described above.

.. _PEP 621: https://peps.python.org/pep-0621/
