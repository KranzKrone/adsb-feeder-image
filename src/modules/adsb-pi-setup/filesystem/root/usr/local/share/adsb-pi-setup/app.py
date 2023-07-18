import filecmp
import io
import json
from operator import is_
import os.path
import pathlib
import re
import shutil
import subprocess
import sys
import zipfile
from functools import partial
from os import path, urandom
from typing import Dict, List, Tuple

from flask import Flask, flash, redirect, render_template, request, send_file, url_for
from utils import (
    ADSBHub,
    Constants,
    Env,
    FlightAware,
    FlightRadar24,
    OpenSky,
    PlaneFinder,
    PlaneWatch,
    RadarBox,
    RadarVirtuel,
    RouteManager,
    SDRDevices,
    System,
    check_restart_lock,
    UltrafeederConfig,
)
from werkzeug.utils import secure_filename


def print_err(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


class AdsbIm:
    def __init__(self):
        self.app = Flask(__name__)
        self.app.secret_key = urandom(16).hex()

        @self.app.context_processor
        def env_functions():
            return {
                "is_enabled": lambda tag: self._constants.is_enabled(tag),
                "env_value_by_tag": lambda tag: self._constants.env_by_tags([tag]).value,  # this one takes a single tag
                "env_value_by_tags": lambda tags: self._constants.env_by_tags(tags).value, # this one takes a list of tags
                "env_values": self._constants.envs,
            }

        self._routemanager = RouteManager(self.app)
        self._constants = Constants()

        self._system = System(constants=self._constants)
        self._sdrdevices = SDRDevices()
        self._ultrafeeder = UltrafeederConfig(constants=self._constants)

        # update Env ultrafeeder to have value self._ultrafeed.generate()
        self._constants.env_by_tags("ultrafeeder_config")._value_call = self._ultrafeeder.generate
        self._other_aggregators = {
            "adsbhub--submit": ADSBHub(self._system),
            "flightaware--submit": FlightAware(self._system),
            "flightradar--submit": FlightRadar24(self._system),
            "opensky--submit": OpenSky(self._system),
            "planefinder--submit": PlaneFinder(self._system),
            "planewatch--submit": PlaneWatch(self._system),
            "radarbox--submit": RadarBox(self._system),
            "radarvirtuel--submit": RadarVirtuel(self._system),
        }
        # fmt: off
        self.proxy_routes = self._constants.proxy_routes
        self.app.add_url_rule("/propagateTZ", "propagateTZ", self.get_tz)
        self.app.add_url_rule("/restarting", "restarting", self.restarting)
        self.app.add_url_rule("/restart", "restart", self.restart, methods=["GET", "POST"])
        self.app.add_url_rule("/backup", "backup", self.backup)
        self.app.add_url_rule("/backupexecute", "backupexecute", self.backup_execute)
        self.app.add_url_rule("/restore", "restore", self.restore, methods=["GET", "POST"])
        self.app.add_url_rule("/executerestore", "executerestore", self.executerestore)
        self.app.add_url_rule("/advanced", "advanced", self.advanced, methods=["GET", "POST"])
        self.app.add_url_rule("/expert", "expert", self.expert, methods=["GET", "POST"])
        self.app.add_url_rule("/aggregators", "aggregators", self.aggregators, methods=["GET", "POST"])
        self.app.add_url_rule("/", "director", self.director, methods=["GET", "POST"])
        self.app.add_url_rule("/index", "index", self.index)
        self.app.add_url_rule("/setup", "setup", self.setup, methods=["GET", "POST"])
        self.app.add_url_rule("/update", "update", self.update, methods=["POST"])
        self.app.add_url_rule("/api/sdr_info", "sdr_info", self.sdr_info)
        # fmt: on

    def run(self):
        self._routemanager.add_proxy_routes(self.proxy_routes)
        debug = os.environ.get("ADSBIM_DEBUG") is not None
        self._debug_cleanup()
        self.app.run(host="0.0.0.0", port=80, debug=debug)

    def _debug_cleanup(self):
        """
        This is a debug function to clean up the docker-starting.lock file
        """
        # rm /opt/adsb/docker-starting.lock
        try:
            os.remove("/opt/adsb/docker-starting.lock")
        except FileNotFoundError:
            pass

    def get_tz(self):
        browser_timezone = request.args.get("tz")
        # Some basic check that it looks something like Europe/Rome
        if not re.match(r"^[A-Z][a-z]+/[A-Z][a-z]+$", browser_timezone):
            return "invalid"
        # Add to .env
        self._constants.env("FEEDER_TZ").value = browser_timezone
        # Set it as datetimectl too
        try:
            subprocess.run(
                f"timedatectl set-timezone {browser_timezone}", shell=True, check=True
            )
        except subprocess.SubprocessError:
            print_err("failed to set up timezone")

        return render_template("setup.html")

    def restarting(self):
        return render_template("restarting.html")

    def restart(self):
        if request.method == "POST":
            resp = self._system._restart.restart_systemd()
            return "restarting" if resp else "already restarting"
        if request.method == "GET":
            return self._system._restart.state

    def backup(self):
        return render_template("/backup.html")

    def backup_execute(self):
        data = self._system.backup()
        return send_file(
            data,
            mimetype="application/zip",
            as_attachment=True,
            download_name="adsb-feeder-config.zip",
        )

    def restore(self):
        if request.method == "POST":
            # check if the post request has the file part
            if "file" not in request.files:
                flash("No file submitted")
                return redirect(request.url)
            file = request.files["file"]
            # If the user does not select a file, the browser submits an
            # empty file without a filename.
            if file.filename == "":
                flash("No file selected")
                return redirect(request.url)
            if file.filename.endswith(".zip"):
                filename = secure_filename(file.filename)
                restore_path = pathlib.Path("/opt/adsb/restore")
                restore_path.mkdir(mode=0o644, exist_ok=True)
                file.save(restore_path / filename)
                print_err(f"saved restore file to {restore_path / filename}")
                return redirect(url_for("executerestore", zipfile=filename))
            else:
                flash("Please only submit ADSB Feeder Image backup files")
                return redirect(request.url)
        else:
            return render_template("/restore.html")

    def executerestore(self):
        if request.method == "GET":
            # the user has uploaded a zip file and we need to take a look.
            # be very careful with the content of this zip file...
            filename = request.args["zipfile"]
            adsb_path = pathlib.Path("/opt/adsb")
            restore_path = pathlib.Path("/opt/adsb/restore")
            restored_files: List[str] = []
            with zipfile.ZipFile(restore_path / filename, "r") as restore_zip:
                for name in restore_zip.namelist():
                    print_err(f"found file {name} in archive")
                    # only accept the .env file and simple .yml filenames
                    if (
                        name != ".env"
                        and not name.startswith("ultrafeeder/")
                        and (not name.endswith(".yml") or name != secure_filename(name))
                    ):
                        continue
                    restore_zip.extract(name, restore_path)
                    restored_files.append(name)
            # now check which ones are different from the installed versions
            changed: List[str] = []
            unchanged: List[str] = []
            for name in restored_files:
                if not name.startswith("ultrafeeder/") and os.path.isfile(
                    adsb_path / name
                ):
                    if filecmp.cmp(adsb_path / name, restore_path / name):
                        print_err(f"{name} is unchanged")
                        unchanged.append(name)
                    else:
                        print_err(f"{name} is different from current version")
                        changed.append(name)
                elif name == "ultrafeeder/":
                    changed.append("ultrafeeder")
            return render_template("/restoreexecute.html")
        else:
            # they have selected the files to restore
            restore_path = pathlib.Path("/opt/adsb/restore")
            adsb_path = pathlib.Path("/opt/adsb")
            for name in request.form.keys():
                print_err(f"restoring {name}")
                shutil.move(adsb_path / name, restore_path / (name + ".dist"))
                shutil.move(restore_path / name, adsb_path / name)
            return redirect(
                "/advanced"
            )  # that's a good place from where the user can continue

    def base_is_configured(self):
        base_config: set[Env] = {
            env for env in self._constants._env if env.is_mandatory
        }
        for env in base_config:
            if env.value == None:
                print_err(f"base_is_configured: {env} isn't set up yet")
                return False
        return True

    def sdr_info(self):
        self._sdrdevices._ensure_populated()
        # get our guess for the right SDR to frequency mapping
        # and then update with the actual settings
        frequencies: Dict[str, str] = self._sdrdevices.addresses_per_frequency
        for freq in [1090, 978]:
            setting = self._constants.env_by_tags(f"{freq}serial")
            if setting and setting.value != "":
                frequencies[freq] = setting.value
        return json.dumps(
            {
                "sdrdevices": [sdr._json for sdr in self._sdrdevices.sdrs],
                "frequencies": frequencies,
            }
        )

    @check_restart_lock
    def advanced(self):
        if request.method == "POST":
            return self.update()

        # just in case things have changed (the user plugged in a new device for example)
        self._sdrdevices._ensure_populated()
        return render_template("advanced.html")

    def update(self):
        description = """
            This is the one endpoint that handles all the updates coming in from the UI.
            It walks through the form data and figures out what to do about the information provided.
        """
        # in the HTML, every input field needs to have a name that is concatenated by "--"
        # and that matches the tags of one Env
        form: Dict = request.form
        seen_go = False
        allow_insecure = not self._constants.is_enabled("secure_image")
        for key, value in form.items():
            print_err(f"handling {key} -> {value} (allow insecure is {allow_insecure})")
            # this seems like cheating... let's capture all of the submit buttons
            if value == "go":
                seen_go = True
                if key == "shutdown":
                    # do shutdown
                    self._system.halt()
                    return "Asked the system to halt. This can take several minutes to complete, and some boards don't power off."
                if key == "reboot":
                    # initiate reboot
                    self._system.reboot()
                    return "Asked the system to reboot. This can take a while, please try to refresh in about a minute or two."
                if key == "secure_image":
                    self._constants.env_by_tags("secure_image").value = True
                    self.secure_image()
                if key == "update":
                    # this needs a lot more checking and safety, but for now, just go
                    cmdline = "/usr/bin/docker-update-adsb-im"
                    subprocess.run(cmdline, timeout=600.0, shell=True)
                if key == "update_feeder_aps":
                    cmdline = "/usr/bin/feeder-update"
                    subprocess.run(cmdline, timeout=600.0, shell=True)
                if key == "nightly_update" or key == "zerotier":
                    # this will be handled through the separate key/value pairs
                    pass
                continue
            if value == "stay":
                if key in self._other_aggregators:
                    is_successful = False
                    base = key.replace("--submit", "")
                    aggregator_argument = form.get(f"{base}--key", None)
                    if base == "opensky":
                        user = form.get(f"{base}--user", None)
                        aggregator_argument += f"::{user}"
                    aggregator_object = self._other_aggregators[key]
                    try:
                        is_successful = aggregator_object._activate(aggregator_argument)
                    except Exception as e:
                        print_err(f"error activating {key}: {e}")
                    if not is_successful:
                        print_err(f"did not successfully enable {base}")

                # we had the magic value of 'go' - so we should be done with this one
                continue
            # now handle other form input
            e = self._constants.env_by_tags(key.split("--"))
            if e:
                if allow_insecure and key == "ssh_pub":
                    ssh_dir = pathlib.Path("/root/.ssh")
                    ssh_dir.mkdir(mode=0o700, exist_ok=True)
                    with open(ssh_dir / "authorized_keys", "a+") as authorized_keys:
                        authorized_keys.write(f"{value}\n")
                    self._constants.env_by_tags("ssh_configured").value = True
                if key == "zerotierid":
                    try:
                        subprocess.call("/usr/bin/systemctl enable --now zerotier-one", shell=True)
                        subprocess.call(f"/usr/sbin/zerotier-cli join {value}", shell=True)
                    except:
                        print_err("exception trying to set up zerorier - giving up")
                e.value = value
        # done handling the input data
        # what implied settings do we have (and could we simplify them?)
        if self._constants.env_by_tags("978serial").value:
            self._constants.env_by_tags(["uat978", "is_enabled"]).value = True
            self._constants.env_by_tags("978url").value = "http://dump978/skyaware978"
            self._constants.env_by_tags("978host").value = "dump978"
            self._constants.env_by_tags("978piaware").value = "relay"
        else:
            self._constants.env_by_tags(["uat978", "is_enabled"]).value = False
            self._constants.env_by_tags("978url").value = ""
            self._constants.env_by_tags("978host").value = ""
            self._constants.env_by_tags("978piaware").value = ""

        self._sdrdevices._ensure_populated()
        airspy = any([sdr._type == "airspy" for sdr in self._sdrdevices.sdrs])
        self._constants.env_by_tags(["airspy", "is_enabled"]).value = airspy
        if (len(self._sdrdevices.sdrs) == 1
            and not airspy
            and not self._constants.env_by_tags("978serial").value):
            self._constants.env_by_tags("1090serial").value = self._sdrdevices.sdrs[0]._serial
        rtlsdr = not airspy and self._constants.env_by_tags("1090serial").value != ""
        self._constants.env_by_tags("rtlsdr").value = "rtlsdr" if rtlsdr else ""

        # let's make sure we write out the updated ultrafeeder config
        self._constants.update_env()

        # if the button simply updated some field, stay on the same page
        if not seen_go:
            return redirect(request.url)

        # finally, check if this has given us enouch configuration info to
        # start the containers
        if self.base_is_configured():
            self._constants.env_by_tags(["base_config"]).value = True
            return redirect(url_for("restarting"))
        return redirect(url_for("director"))

    @check_restart_lock
    def expert(self):
        if request.method == "POST":
            return self.update()

        return render_template("expert.html")

    def secure_image(self):
        output: str = ""
        try:
            result = subprocess.run(
                "/usr/bin/secure-image", shell=True, capture_output=True
            )
        except subprocess.TimeoutError as exc:
            output = exc.stdout.decode()
        else:
            output = result.stdout.decode()
        print_err(f"secure_image: {output}")

    @check_restart_lock
    def aggregators(self):
        if request.method == "POST":
            return self.update()

        def uf_enabled(*tags):
            return "checked" if self._constants.is_enabled("ultrafeeder", *tags) else ""
        def others_enabled(*tags):
            return "checked" if self._constants.is_enabled("other_aggregator", *tags) else ""

        return render_template(
            "aggregators.html",
            uf_enabled=uf_enabled,
            others_enabled=others_enabled,
        )

    def director(self):
        # figure out where to go:
        if request.method == "POST":
            return self.update()
        if not self._constants.is_enabled("base_config"):
            return self.setup()

        # If we have more than one SDR, or one of them is an airspy,
        # we need to go to advanced - unless we have at least one of the serials set up
        # for 978 or 1090 reporting
        self._sdrdevices._ensure_populated()
        if ((len(self._sdrdevices) > 1 or any([sdr._type == "airspy" for sdr in self._sdrdevices.sdrs]))
            and not (self._constants.env_by_tags("1090serial").value or self._constants.env_by_tags("978serial").value)):
            return self.advanced()

        # if the user chose to individually pick aggregators but hasn't done so,
        # they need to go to the aggregator page
        if not self._ultrafeeder.enabled_aggregators:
            return self.aggregators()

        return self.index()

    def index(self):
        return render_template("index.html")

    @check_restart_lock
    def setup(self):
        if request.method == "POST" and request.form.get("submit") == "go":
            return self.update()
        return render_template("setup.html")


if __name__ == "__main__":
    AdsbIm().run()
