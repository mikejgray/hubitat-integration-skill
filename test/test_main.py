# pylint: disable=missing-class-docstring,missing-module-docstring,missing-function-docstring
# pylint: disable=invalid-name,protected-access
from ovos_workshop.skills import OVOSSkill
from hubitat_integration_skill import HubitatIntegration
from . import SkillTestCase


class HubitatIntegrationSkillTestCase(SkillTestCase):
    """ActivuSkill unit test class."""

    def test_skill_init(self):
        """Assert that the skill instantiates properly."""
        self.assertIsInstance(self.skill, OVOSSkill)

    def test_dev_api(self) -> None:
        assert isinstance(self.skill, HubitatIntegration)
