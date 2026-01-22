# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

from spack_repo.builtin.build_systems.python import PythonPackage

from spack.package import *


class PyHubcast(PythonPackage):
    """An event driven synchronization application for bridging GitHub and GitLab."""

    homepage = "https://github.com/LLNL/hubcast"
    git = "https://github.com/LLNL/hubcast.git"

    maintainers("alecbcs", "cmelone")

    license("Apache-2.0")

    version("main", branch="main")

    depends_on("python@3.10:", type=("build", "run"))

    depends_on("py-hatchling", type="build")

    depends_on("py-aiohttp", type=("build", "run"))
    depends_on("py-aiojobs", type=("build", "run"))
    depends_on("py-gidgethub", type=("build", "run"))
    depends_on("py-gidgetlab+aiohttp", type=("build", "run"))
    depends_on("py-repligit", type=("build", "run"))
    depends_on("py-pyyaml", type=("build", "run"))
    depends_on("py-python-ldap", type=("build", "run"))
