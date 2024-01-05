import shutil
import unittest
from json import dumps
from os import environ, getenv, makedirs
from os.path import dirname, isdir, join
from typing import Optional, cast
from unittest.mock import Mock

from ovos_bus_client.client import MessageBusClient
from ovos_utils.log import LOG
from ovos_utils.messagebus import FakeBus
from ovos_workshop.skills.base import BaseSkill


def get_skill_object(
    skill_entrypoint: str, bus: FakeBus, skill_id: str, config_patch: Optional[dict] = None
) -> BaseSkill:
    """
    Get an initialized skill object by entrypoint with the requested skill_id.
    @param skill_entrypoint: Skill plugin entrypoint or directory path
    @param bus: FakeBus instance to bind to skill for testing
    @param skill_id: skill_id to initialize skill with
    @returns: Initialized skill object
    """
    if config_patch:
        from ovos_config.config import update_mycroft_config

        update_mycroft_config(config_patch)
    if isdir(skill_entrypoint):
        LOG.info(f"Loading local skill: {skill_entrypoint}")
        from ovos_workshop.skill_launcher import SkillLoader

        loader = SkillLoader(cast(MessageBusClient, bus), skill_entrypoint, skill_id)
        if loader.load() and loader.instance:
            return loader.instance
    from ovos_plugin_manager.skills import find_skill_plugins

    plugins = find_skill_plugins()
    if skill_entrypoint not in plugins:
        raise ValueError(f"Requested skill not found: {skill_entrypoint}")
    plugin = plugins[skill_entrypoint]
    skill = plugin(bus=bus, skill_id=skill_id)
    return skill


class SkillTestCase(unittest.TestCase):
    # Define test directories
    test_fs = join(dirname(__file__), "skill_fs")
    data_dir = join(test_fs, "data")
    conf_dir = join(test_fs, "config")
    environ["XDG_DATA_HOME"] = data_dir
    environ["XDG_CONFIG_HOME"] = conf_dir
    makedirs(join(conf_dir, "mycroft/skills/skill-activu.neongeckocom"), exist_ok=True)
    with open(join(conf_dir, "mycroft/skills/skill-activu.neongeckocom/settings.json"), "w+", encoding="utf-8") as f:
        test_settings = {
            "__mycroft_skill_firstrun": False,
            "endpoint": getenv("ENDPOINT"),
            "api_key": getenv("API_KEY"),
        }
        f.write(dumps(test_settings))

    # Define static parameters
    bus = FakeBus()
    bus.run_forever()
    test_skill_id = "skill-activu.neongeckocom"

    skill = None

    @classmethod
    def setUpClass(cls) -> None:
        # Get test skill
        skill_entrypoint = getenv("TEST_SKILL_ENTRYPOINT")
        if not skill_entrypoint:
            from ovos_plugin_manager.skills import find_skill_plugins

            skill_entrypoints = list(find_skill_plugins().keys())
            assert len(skill_entrypoints) == 1
            skill_entrypoint = skill_entrypoints[0]
        if not skill_entrypoint:
            raise ValueError("No skill entrypoint found, cannot test")

        cls.skill = get_skill_object(skill_entrypoint=skill_entrypoint, skill_id=cls.test_skill_id, bus=cls.bus)
        # Override speak and speak_dialog to test passed arguments
        cls.skill.speak = Mock()
        cls.skill.speak_dialog = Mock()

    def setUp(self):
        if self.skill:
            self.skill.speak.reset_mock()
            self.skill.speak_dialog.reset_mock()
        else:
            raise ValueError("Skill not loaded, cannot setup tests")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.test_fs)
