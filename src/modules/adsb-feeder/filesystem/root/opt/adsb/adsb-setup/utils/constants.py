# dataclass
from dataclasses import dataclass
from os import getenv, path
from pathlib import Path
import re
from uuid import uuid4

from .environment import ENV_FILE_PATH, ENV_FLAG_FILE_PATH, Env, is_true
from .netconfig import NetConfig, UltrafeederConfig
from .util import print_err


@dataclass
class Constants:
    def __new__(cc):
        if not hasattr(cc, "instance"):
            cc.instance = super(Constants, cc).__new__(cc)
        return cc.instance

    data_path = Path("/opt/adsb")
    config_path = data_path / "config"
    env_file_path = config_path / ".env"
    version_file = data_path / "adsb.im.version"
    secure_image_path = data_path / "adsb.im.secure_image"
    is_feeder_image = True
    ultrafeeder = None
    ultrafeeder_micro = []

    _proxy_routes = [
        # endpoint, port, url_path
        ["/map/", "TAR1090", "/"],
        ["/tar1090/", "TAR1090", "/"],
        ["/graphs1090/", "TAR1090", "/graphs1090/"],
        ["/graphs/", "TAR1090", "/graphs1090/"],
        ["/stats/", "TAR1090", "/graphs1090/"],
        ["/piaware/", "PIAWAREMAP", "/"],
        ["/fa/", "PIAWAREMAP", "/"],
        ["/flightaware/", "PIAWAREMAP", "/"],
        ["/piaware-stats/", "PIAWARESTAT", "/"],
        ["/pa-stats/", "PIAWARESTAT", "/"],
        ["/fa-stats/", "PIAWARESTAT", "/"],
        ["/fa-status/", "PIAWARESTAT", "/"],
        ["/fa-status.json/", "PIAWARESTAT", "/status.json"],
        ["/fr-status/", "FLIGHTRADAR", "/"],
        ["/fr/", "FLIGHTRADAR", "/"],
        ["/fr24/", "FLIGHTRADAR", "/"],
        ["/fr24-monitor.json", "FLIGHTRADAR", "/monitor.json"],
        ["/flightradar/", "FLIGHTRADAR", "/"],
        ["/flightradar24/", "FLIGHTRADAR", "/"],
        ["/planefinder/", "PLANEFINDER", "/"],
        ["/planefinder-stat/", "PLANEFINDER", "/stats.html"],
        ["/dump978/", "UAT978", "/skyaware978/"],
        ["/logs/", "DAZZLE", "/"],
        ["/dozzle/", "DAZZLE", "/"],
        ["/config/", "DAZZLE", "/setup"],
    ]

    @property
    def proxy_routes(self):
        ret = []
        for [endpoint, _env, path] in self._proxy_routes:
            env = "AF_" + _env.upper() + "_PORT"
            ret.append([endpoint, self.env(env).value, path])
        return ret

    # these are the default values for the env file

    netconfigs = {
        "adsblol": NetConfig(
            "adsb,feed.adsb.lol,30004,beast_reduce_plus_out",
            "mlat,feed.adsb.lol,31090,39001",
            has_policy=True,
        ),
        "flyitaly": NetConfig(
            "adsb,dati.flyitalyadsb.com,4905,beast_reduce_plus_out",
            "mlat,dati.flyitalyadsb.com,30100,39002",
            has_policy=True,
        ),
        "adsbx": NetConfig(
            "adsb,feed1.adsbexchange.com,30004,beast_reduce_plus_out",
            "mlat,feed.adsbexchange.com,31090,39003",
            has_policy=True,
        ),
        "tat": NetConfig(
            "adsb,feed.theairtraffic.com,30004,beast_reduce_plus_out",
            "mlat,feed.theairtraffic.com,31090,39004",
            has_policy=False,
        ),
        "planespotters": NetConfig(
            "adsb,feed.planespotters.net,30004,beast_reduce_plus_out",
            "mlat,mlat.planespotters.net,31090,39005",
            has_policy=True,
        ),
        "adsbfi": NetConfig(
            "adsb,feed.adsb.fi,30004,beast_reduce_plus_out",
            "mlat,feed.adsb.fi,31090,39007",
            has_policy=True,
        ),
        "avdelphi": NetConfig(
            "adsb,data.avdelphi.com,24999,beast_reduce_plus_out",
            "",
            has_policy=True,
        ),
        # "flyovr": NetConfig(
        #    "adsb,feed.flyovr.io,30004,beast_reduce_plus_out",
        #    "",
        #    has_policy=False,
        # ),
        "radarplane": NetConfig(
            "adsb,feed.radarplane.com,30001,beast_reduce_plus_out",
            "mlat,feed.radarplane.com,31090,39010",
            has_policy=True,
        ),
        "hpradar": NetConfig(
            "adsb,skyfeed.hpradar.com,30004,beast_reduce_plus_out",
            "mlat,skyfeed.hpradar.com,31090,39011",
            has_policy=False,
        ),
        "alive": NetConfig(
            "adsb,feed.airplanes.live,30004,beast_reduce_plus_out",
            "mlat,feed.airplanes.live,31090,39012",
            has_policy=True,
        ),
    }
    # we have four different types of "feeders":
    # 1. integrated feeders (single SBC where one Ultrafeeder collects from SDR and send to aggregator)
    # 2. micro feeders (SBC with SDR(s) attached, talking to a stage2 micro proxy)
    # 3. stage2 micro proxies (run on the stage2 system, each talking to a micro feeder and to aggregators)
    # 4. stage2 aggregator (showing a combined map of the micro feeders)
    # most feeder related values are lists with element 0 being used either for an
    # integrated feeder, a micro feeder, or the aggregator in a stage2 setup, and
    # elements 1 .. num_micro_sites are used for the micro-proxy instances
    _env = {
        # Mandatory site data
        Env("FEEDER_LAT", default=[], mandatory=True, tags=["lat"]),
        Env("FEEDER_LONG", default=[], mandatory=True, tags=["lng"]),
        Env("FEEDER_ALT_M", default=[], mandatory=True, tags=["alt"]),
        Env("FEEDER_TZ", default=[], mandatory=True, tags=["form_timezone"]),
        Env("SITE_NAME", default=[], mandatory=True, tags=["site_name"]),
        Env("MAP_NAME", default=[], mandatory=True, tags=["map_name"]),
        #
        # SDR settings are only valid on an integrated feeder or a micro feeder, not on stage2
        Env("FEEDER_RTL_SDR", default="rtlsdr", tags=["rtlsdr"]),
        Env(
            "FEEDER_ENABLE_BIASTEE",
            default=False,
            tags=["biast", "is_enabled", "false_is_empty"],
        ),
        Env(
            "FEEDER_ENABLE_UATBIASTEE",
            default=False,
            tags=["uatbiast", "is_enabled", "false_is_empty"],
        ),
        Env("FEEDER_READSB_GAIN", default="autogain", tags=["gain"]),
        Env("FEEDER_AIRSPY_GAIN", default="auto", tags=["gain_airspy"]),
        Env("UAT_SDR_GAIN", default="autogain", tags=["uatgain"]),
        Env("FEEDER_SERIAL_1090", tags=["1090serial"]),
        Env("FEEDER_SERIAL_978", tags=["978serial"]),
        Env("FEEDER_UNUSED_SERIAL_0", tags=["other-0"]),
        Env("FEEDER_UNUSED_SERIAL_1", tags=["other-1"]),
        Env("FEEDER_UNUSED_SERIAL_2", tags=["other-2"]),
        Env("FEEDER_UNUSED_SERIAL_3", tags=["other-3"]),
        #
        # Ultrafeeder config, used for all 4 types of Ultrafeeder instances
        Env("FEEDER_ULTRAFEEDER_CONFIG", default=[], tags=["ultrafeeder_config"]),
        Env("ADSBLOL_UUID", default=[], tags=["adsblol_uuid"]),
        Env("ULTRAFEEDER_UUID", default=[], tags=["ultrafeeder_uuid"]),
        #
        # Global settings, not differentiated per micro feeder
        Env("MLAT_PRIVACY", default=True, tags=["mlat_privacy", "is_enabled"]),
        Env(
            "FEEDER_TAR1090_USEROUTEAPI",
            default="1",
            tags=["route_api", "is_enabled", "false_is_zero"],
        ),
        Env(  # this has no UI component, but we want to enable the advanced user to modify it in .env
            "TAR1090_RANGE_OUTLINE_DASH",
            default="[2,3]",
            tags=["range_outline_dash"],
        ),
        # 978, airspy, others for integrated feeders and micro feeders
        Env(  # start the 978 container
            "FEEDER_ENABLE_UAT978", default=[False], tags=["uat978", "is_enabled"]
        ),
        Env(  # add the URL to the dump978 map
            "FEEDER_URL_978", default=[""], tags=["978url"]
        ),
        Env(  # hostname ultrafeeder uses to get 978 data
            "FEEDER_UAT978_HOST", default=[""], tags=["978host"]
        ),
        Env(  # magic setting for piaware to get 978 data
            "FEEDER_PIAWARE_UAT978", default=[""], tags=["978piaware"]
        ),
        Env(
            "AF_IS_AIRSPY_ENABLED",
            tags=["airspy", "is_enabled"],
        ),
        # Misc
        Env(
            "_ADSBIM_HEYWHATSTHAT_ENABLED",
            default=[False],
            tags=["heywhatsthat", "is_enabled"],
        ),
        Env(
            "FEEDER_HEYWHATSTHAT_ID",
            default=[""],
            tags=["heywhatsthat_id", "key"],
        ),
        # Ultrafeeder config
        Env(
            "_ADSBIM_STATE_IS_ULTRAFEEDER_ADSBLOL_ENABLED",
            default=[False],
            tags=["adsblol", "ultrafeeder", "is_enabled"],
        ),
        Env(
            "_ADSBIM_STATE_IS_ULTRAFEEDER_FLYITALYADSB_ENABLED",
            default=[False],
            tags=["flyitaly", "ultrafeeder", "is_enabled"],
        ),
        Env(
            "_ADSBIM_STATE_IS_ULTRAFEEDER_ADSBX_ENABLED",
            default=[False],
            tags=["adsbx", "ultrafeeder", "is_enabled"],
        ),
        Env(
            "_ADSBIM_STATE_ADSBX_FEEDER_ID",
            default=[False],
            tags="adsbxfeederid",
        ),
        Env(
            "_ADSBIM_STATE_IS_ULTRAFEEDER_TAT_ENABLED",
            default=[False],
            tags=["tat", "ultrafeeder", "is_enabled"],
        ),
        Env(
            "_ADSBIM_STATE_IS_ULTRAFEEDER_PLANESPOTTERS_ENABLED",
            default=[False],
            tags=["planespotters", "ultrafeeder", "is_enabled"],
        ),
        Env(
            "_ADSBIM_STATE_IS_ULTRAFEEDER_ADSBFI_ENABLED",
            default=[False],
            tags=["adsbfi", "ultrafeeder", "is_enabled"],
        ),
        Env(
            "_ADSBIM_STATE_IS_ULTRAFEEDER_AVDELPHI_ENABLED",
            default=[False],
            tags=["avdelphi", "ultrafeeder", "is_enabled"],
        ),
        # Env(
        #    "_ADSBIM_STATE_IS_ULTRAFEEDER_FLYOVR_ENABLED",
        #    default=[False],
        #    tags=["flyovr", "ultrafeeder", "is_enabled"],
        # ),
        Env(
            "_ADSBIM_STATE_IS_ULTRAFEEDER_RADARPLANE_ENABLED",
            default=[False],
            tags=["radarplane", "ultrafeeder", "is_enabled"],
        ),
        Env(
            "_ADSBIM_STATE_IS_ULTRAFEEDER_HPRADAR_ENABLED",
            default=[False],
            tags=["hpradar", "ultrafeeder", "is_enabled"],
        ),
        Env(
            "_ADSBIM_STATE_IS_ULTRAFEEDER_ALIVE_ENABLED",
            default=[False],
            tags=["alive", "ultrafeeder", "is_enabled"],
        ),
        # other aggregators
        Env(
            "AF_IS_FLIGHTRADAR24_ENABLED",
            default=[False],
            tags=["other_aggregator", "is_enabled", "flightradar"],
        ),
        Env(
            "AF_IS_PLANEWATCH_ENABLED",
            default=[False],
            tags=["other_aggregator", "is_enabled", "planewatch"],
        ),
        Env(
            "AF_IS_FLIGHTAWARE_ENABLED",
            default=[False],
            tags=["other_aggregator", "is_enabled", "flightaware"],
        ),
        Env(
            "AF_IS_RADARBOX_ENABLED",
            default=[False],
            tags=["other_aggregator", "is_enabled", "radarbox"],
        ),
        Env(
            "AF_IS_PLANEFINDER_ENABLED",
            default=[False],
            tags=["other_aggregator", "is_enabled", "planefinder"],
        ),
        Env(
            "AF_IS_ADSBHUB_ENABLED",
            default=[False],
            tags=["other_aggregator", "is_enabled", "adsbhub"],
        ),
        Env(
            "AF_IS_OPENSKY_ENABLED",
            default=[False],
            tags=["other_aggregator", "is_enabled", "opensky"],
        ),
        Env(
            "AF_IS_RADARVIRTUEL_ENABLED",
            default=[False],
            tags=["other_aggregator", "is_enabled", "radarvirtuel"],
        ),
        Env(
            "AF_IS_1090UK_ENABLED",
            default=[False],
            tags=["other_aggregator", "is_enabled", "1090uk"],
        ),
        # Other aggregators keys
        Env(
            "FEEDER_FR24_SHARING_KEY",
            default=[""],
            tags=["flightradar", "key"],
        ),
        Env(
            "FEEDER_FR24_UAT_SHARING_KEY",
            default=[""],
            tags=["flightradar_uat", "key"],
        ),
        Env(
            "FEEDER_PIAWARE_FEEDER_ID",
            default=[""],
            tags=["flightaware", "key"],
        ),
        Env(
            "FEEDER_RADARBOX_SHARING_KEY",
            default=[""],
            tags=["radarbox", "key"],
        ),
        Env(
            "FEEDER_RADARBOX_SN",
            default=[""],
            tags=["radarbox", "sn"],
        ),
        Env(  # only on integrated or micro feeders
            "FEEDER_RB_CPUINFO_HACK",
            default="",
            tags=["rbcpuhack"],
        ),
        Env(  # only on integrated or micro feeders
            "FEEDER_RB_THERMAL_HACK",
            default=[""],
            tags=["rbthermalhack"],
        ),
        Env(
            "FEEDER_PLANEFINDER_SHARECODE",
            default=[""],
            tags=["planefinder", "key"],
        ),
        Env(
            "FEEDER_ADSBHUB_STATION_KEY",
            default=[""],
            tags=["adsbhub", "key"],
        ),
        Env(
            "FEEDER_OPENSKY_USERNAME",
            default=[""],
            tags=["opensky", "user"],
        ),
        Env(
            "FEEDER_OPENSKY_SERIAL",
            default=[""],
            tags=["opensky", "key"],
        ),
        Env(
            "FEEDER_RV_FEEDER_KEY",
            default=[""],
            tags=["radarvirtuel", "key"],
        ),
        Env(
            "FEEDER_PLANEWATCH_API_KEY",
            default=[""],
            tags=["planewatch", "key"],
        ),
        Env(
            "FEEDER_1090UK_API_KEY",
            default=[""],
            tags=["1090uk", "key"],
        ),
        # ADSB.im specific
        Env(  # all, privacy, individual, micro (the latter indicates this is a micro feeder)
            # for sanity reason this is used for all stage2 proxies - same value
            "_ADSBIM_AGGREGATORS_SELECTION",
            tags=["aggregators"],
        ),
        Env(  # always of the software stack that is running, regardless of feeder type
            "_ADSBIM_BASE_VERSION",
            tags=["base_version", "norestore"],
        ),
        Env(  # always the board where the software stack is running
            "_ADSBIM_STATE_BOARD_NAME",
            tags=["board_name", "norestore"],
        ),
        # ports used by our proxy system
        # only really important when running as app, which means integrated feeder or stage2
        Env("AF_WEBPORT", default=80, tags=["webport"]),
        Env("AF_DAZZLE_PORT", default=9999, tags=["dazzleport"]),
        Env("AF_TAR1090_PORT", default=8080, tags=["tar1090port"]),
        Env("AF_UAT978_PORT", default=9780, tags=["uatport"]),
        Env("AF_PIAWAREMAP_PORT", default=8081, tags=["piamapport"]),
        Env("AF_PIAWARESTAT_PORT", default=8082, tags=["piastatport"]),
        Env("AF_FLIGHTRADAR_PORT", default=8754, tags=["frport"]),
        Env("AF_PLANEFINDER_PORT", default=30053, tags=["pfport"]),
        Env("_ADSBIM_STATE_PACKAGE", tags=["pack", "norestore"]),
        Env(
            "_ADSBIM_STATE_IMAGE_NAME",
            # somehow I can't make a path relative to data_path work here...
            default_call=lambda: (
                Path("/opt/adsb/feeder-image.name").read_text()
                if Path("/opt/adsb/feeder-image.name").exists()
                else "ADS-B Feeder Image prior to v0.12"
            ),
            tags=["image_name", "norestore"],
        ),
        # legacy secure image state, now handled via separate file
        # keep it around to handle updates from before the changeover
        # and easy checks in webinterface
        Env(
            "AF_IS_SECURE_IMAGE",
            default=False,
            tags=["secure_image", "is_enabled"],
        ),
        # specific to the board this is running on, not per feeder
        Env(
            "_ADSBIM_STATE_IS_SSH_CONFIGURED",
            tags=["ssh_configured", "is_enabled", "norestore"],
        ),
        Env(
            "_ADSB_STATE_SSH_KEY",
            tags=["ssh_pub", "key", "norestore"],
        ),
        Env(
            "AF_IS_BASE_CONFIG_FINISHED",
            default=False,
            tags=["base_config", "is_enabled"],
        ),
        Env(
            "_ADSBIM_STATE_AGGREGATORS_CHOSEN",
            default=False,
            tags=["aggregators_chosen"],
        ),
        Env(
            "AF_IS_NIGHTLY_BASE_UPDATE_ENABLED",
            tags=["nightly_base_update", "is_enabled"],
        ),
        Env(
            "AF_IS_NIGHTLY_FEEDER_UPDATE_ENABLED",
            tags=["nightly_feeder_update", "is_enabled"],
        ),
        Env(
            "AF_IS_NIGHTLY_CONTAINER_UPDATE_ENABLED",
            tags=["nightly_container_update", "is_enabled"],
        ),
        Env(
            "_ADSBIM_STATE_ZEROTIER_KEY",
            tags=["zerotierid", "key"],
        ),
        Env(
            "_ADSBIM_STATE_TAILSCALE_LOGIN_LINK",
            tags=["tailscale_ll"],
            default="",
        ),
        Env(
            "_ADSBIM_STATE_TAILSCALE_NAME",
            tags=["tailscale_name"],
            default="",
        ),
        Env(
            "_ADSBIM_STATE_TAILSCALE_EXTRA_ARGS",
            tags=["tailscale_extras"],
        ),
        Env(
            "_ADSBIM_STATE_EXTRA_ENV",
            tags=["ultrafeeder_extra_env"],
        ),
        # Container images
        # -- these names are magic and are used in yaml files and the structure
        #    of these names is used in scripting around that
        Env("ULTRAFEEDER_CONTAINER", tags=["ultrafeeder", "container"]),
        Env("FR24_CONTAINER", tags=["flightradar", "container"]),
        Env("FA_CONTAINER", tags=["flightaware", "container"]),
        Env("RB_CONTAINER", tags=["radarbox", "container"]),
        Env("PF_CONTAINER", tags=["planefinder", "container"]),
        Env("AH_CONTAINER", tags=["adsbhub", "container"]),
        Env("OS_CONTAINER", tags=["opensky", "container"]),
        Env("RV_CONTAINER", tags=["radarvirtuel", "container"]),
        Env("PW_CONTAINER", tags=["planewatch", "container"]),
        Env("TNUK_CONTAINER", tags=["1090uk", "container"]),
        # per system config
        Env(
            "_ADSBIM_STATE_ULTRAFEEDER_EXTRA_ARGS",
            tags=["ultrafeeder_extra_args"],
        ),
        Env(
            "FEEDER_TAR1090_ENABLE_AC_DB",
            default=True,
            tags=["tar1090_ac_db", "is_enabled"],
        ),
        Env(
            "FEEDER_MLATHUB_DISABLE",
            default=False,
            tags=["mlathub_disable", "is_enabled"],
        ),
        Env(
            "_ADSBIM_STATE_REMOTE_SDR",
            tags=["remote_sdr"],
        ),
        Env(
            "_ADSBIM_STATE_LAST_DNS_CHECK",
            tags=["dns_state", "norestore"],
        ),
        Env(
            "_ADSBIM_STATE_FEEDER_IP",
            tags=["feeder_ip", "norestore"],
        ),
        Env(
            "_ADSBIM_STATE_UNDER_VOLTAGE",
            tags=["under_voltage", "norestore"],
        ),
        Env(
            "_ADSBIM_STATE_LOW_DISK",
            tags=["low_disk", "norestore"],
        ),
        Env(
            "AF_IS_STAGE2",
            default=False,
            tags=["stage2", "is_enabled"],
        ),
        Env(
            "AF_NUM_MICRO_SITES",
            default=0,
            tags=["num_micro_sites"],
        ),
        Env(
            "_ADSBIM_STATE_STAGE2_LISTENERS",
            default=[],
            tags=["stage2_listeners"],
        ),
        Env("AF_MICRO_IP", default=[], tags=["mf_ip"]),
        Env("MF_FEEDER_LAT", default=[], tags=["mf_lat"]),
        Env("MF_FEEDER_LONG", default=[], tags=["mf_lng"]),
        Env("MF_FEEDER_ALT_M", default=[], tags=["mf_alt"]),
        Env("MF_FEEDER_TZ", default=[], tags=["mf_timezone"]),
        Env("MF_FEEDER_VERSION", default=[], tags=["mf_version"]),
    }

    @property
    def envs(self):
        return {e.name: e.value for e in self._env}

    # helper function to find env by name
    def env(self, name: str):
        for e in self._env:
            if e.name == name:
                return e
        return None

    # helper function to find env by tags
    # Return only if there is one env with all the tags,
    # Raise error if there are more than one match
    def env_by_tags(self, _tags):
        if type(_tags) == str:
            tags = [_tags]
        elif type(_tags) == list:
            tags = _tags
        else:
            raise Exception(
                f"env_by_tags called with invalid argument {_tags} of type {type(_tags)}"
            )
        matches = []
        if not tags:
            return None
        for e in self._env:
            if not e.tags:
                print_err(f"{e} has no tags")
            if all(t in e.tags for t in tags):
                matches.append(e)
        if len(matches) == 0:
            return None
        if len(matches) > 1:
            print_err(f"More than one match for tags {tags}")
            for e in matches:
                print_err(f"  {e}")
        return matches[0]

    def _get_enabled_env_by_tags(self, *tags):
        # we append is_enabled to tags
        taglist = list(tags)
        taglist.append("is_enabled")
        return self.env_by_tags(taglist)

    # helper function to see if something is enabled
    def is_enabled(self, *tags):
        e = self._get_enabled_env_by_tags(tags)
        return e and e.value

    # helper function to see if list element is enabled
    def list_is_enabled(self, *tags, idx):
        e = self._get_enabled_env_by_tags(tags)
        print_err(f"list_is_enabled {tag} {idx} {e}")
        return e.list_get(idx) if e else ""

    # helper function to get everything that needs to be written out written out
    def writeback_env(self):
        print_err("writing out the .env file")
        # we need to grap a (basically random) Env object to be able to use the
        # object methods:
        env = next(iter(self._env))
        env_vars = (
            env._get_values_from_env_file()
            if path.exists(ENV_FLAG_FILE_PATH)
            else env._get_values_from_file()
        )
        for e in self._env:
            print_err(f"WRITEBACK {e} with type {type(e._value)}")
            if any(t == "false_is_zero" for t in e.tags):
                env_vars[e.name] = "1" if is_true(e.value) else "0"
            elif any(t == "false_is_empty" for t in e.tags):
                env_vars[e.name] = "True" if is_true(e.value) else ""
            else:
                env_vars[e.name] = e.value
            # make sure we create the ultrafeeder configurations
            if e.name == "MF_FEEDER_ULTRAFEEDER_CONFIG":
                print_err(f"writing the MF Ultrafeeder config ")
                for i in range(self.env("AF_NUM_MICRO_SITES").value):
                    if i >= len(self.ultrafeeder_micro):
                        self.ultrafeeder_micro.append(
                            UltrafeederConfig(constants=self, micro=i)
                        )
                    uc = self.ultrafeeder_micro[i].generate()
                    e.list_set(i, uc)
                    env_vars[f"MF_FEEDER_ULTRAFEEDER_CONFIG_{i}"] = uc
        print_err(f"read in from file and applied any in memory changes: {env_vars}")
        env._write_file(env_vars)

    # make sure our internal data is in sync with the .env file on disk
    def re_read_env(self):
        env_vars = {}
        with open(ENV_FILE_PATH, "r") as env_file:
            for line in env_file.readlines():
                if line.strip().startswith("#"):
                    continue
                key, var = line.partition("=")[::2]
                env_vars[key.strip()] = var.strip()
        # now that we have completed reading them, update each of the Env objects
        for e in self._env:
            if e.name in env_vars:
                e.value = env_vars[e.name]
