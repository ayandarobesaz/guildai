# Copyright 2017 TensorHub, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import absolute_import
from __future__ import division

import logging
import os
import subprocess
import sys

import pkg_resources

import click

import guild
import guild.cli
import guild.plugin
import guild.test
import guild.uat
import guild.util

CHECK_MODS = [
    "pip",
    "psutil",
    "setuptools",
    "twine",
    "yaml",
    "werkzeug",
]

class Check(object):

    def __init__(self, args):
        self.args = args
        self._errors = False

    def error(self):
        self._errors = True

    @property
    def has_error(self):
        return self._errors

def main(args):
    if args.uat:
        _uat_and_exit()
    check = Check(args)
    if not args.no_info:
        _print_info(check)
    if args.all_tests or args.tests:
        _run_tests(check)
    if check.has_error:
        guild.cli.error(
            "there are problems with your Guild setup\n"
            "Refer to the issues above for more information.")

def _uat_and_exit():
    guild.uat.run()
    sys.exit(0)

def _run_tests(check):
    if check.args.all_tests:
        if check.args.tests:
            logging.warning(
                "running all tests (--all-tests specified) - "
                "ignoring individual tests")
        success = guild.test.run_all(skip=check.args.skip)
    elif check.args.tests:
        if check.args.skip:
            logging.warning(
                "running individual tests - ignoring --skip")
        success = guild.test.run(check.args.tests)
    if not success:
        check.error()

def _print_info(check):
    _print_guild_info()
    _print_python_info(check)
    _print_tensorflow_info(check)
    _print_nvidia_tools_info()
    _print_mods_info(check)

def _print_guild_info():
    guild.cli.out("guild_version:             %s" % guild.version())
    guild.cli.out("guild_home:                %s" % _guild_home())
    guild.cli.out("installed_plugins:         %s" % _format_plugins())

def _guild_home():
    return pkg_resources.resource_filename("guild", "")

def _format_plugins():
    return ", ".join([
        name
        for name, _ in sorted(guild.plugin.iter_plugins())
    ])

def _print_python_info(check):
    guild.cli.out("python_version:            %s" % _python_version())
    if check.args.verbose:
        guild.cli.out("python_path:           %s" % _python_path())

def _python_version():
    return sys.version.replace("\n", "")

def _python_path():
    return os.path.pathsep.join(sys.path)

def _print_tensorflow_info(check):
    # Run externally to avoid tf logging to our stderr
    from . import tensorflow_info_main
    cmd = [sys.executable, tensorflow_info_main.__file__]
    env = guild.util.safe_osenv()
    env["PYTHONPATH"] = os.path.pathsep.join(sys.path)
    stderr = None if check.args.verbose else open(os.devnull, "w")
    p = subprocess.Popen(cmd, stderr=stderr, env=env)
    exit_status = p.wait()
    if exit_status != 0:
        check.error()

def _print_nvidia_tools_info():
    guild.cli.out("nvidia_smi_available:      %s" % _nvidia_smi_available())

def _nvidia_smi_available():
    try:
        subprocess.check_output(["which", "nvidia-smi"])
    except (OSError, subprocess.CalledProcessError):
        return "no"
    else:
        return "yes"

def _print_mods_info(check):
    for mod in CHECK_MODS:
        ver = _try_module_version(mod, check)
        space = " " * (18 - len(mod))
        guild.cli.out("%s_version:%s%s" % (mod, space, ver))

def _try_module_version(name, check):
    try:
        mod = __import__(name)
    except ImportError as e:
        check.error()
        return _warn("NOT INSTALLED (%s)" % e)
    else:
        try:
            return mod.__version__
        except AttributeError:
            return _warn("UNKNOWN")

def _warn(msg):
    return click.style(msg, fg="red", bold=True)
