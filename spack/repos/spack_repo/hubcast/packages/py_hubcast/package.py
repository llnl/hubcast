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

    variant("ldap", default=False, description="Enable LDAP account map support")

    depends_on("python@3.11:", type=("build", "run"))
    depends_on("py-hatchling", type="build")
    depends_on("py-aiohttp", type=("build", "run"))
    depends_on("py-aiojobs", type=("build", "run"))
    depends_on("py-pyjwt", type=("build", "run"))
    depends_on("py-gidgethub+aiohttp", type=("build", "run"))
    depends_on("py-gidgetlab@2.1.2:+aiohttp", type=("build", "run"))
    depends_on("py-repligit", type=("build", "run"))
    depends_on("py-pyyaml", type=("build", "run"))
    depends_on("py-pydantic", type=("build", "run"))
    depends_on("py-pydantic-settings", type=("build", "run"))
    depends_on("py-python-ldap", type=("build", "run"), when="+ldap")
    depends_on("py-pytest", type="test")
    depends_on("py-pytest-asyncio", type="test")
    depends_on("py-pytest-mock", type="test")

    @run_after("install")
    @on_package_attributes(run_tests=True)
    def install_test(self):
        with working_dir(self.stage.source_path):
            python("-m", "pytest", "tests")
