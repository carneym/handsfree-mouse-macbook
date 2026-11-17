"""A copied, signed app must save preferences outside its read-only bundle."""
from pathlib import Path
import tempfile
import unittest
from preferences import profile_path, save_profile, load_profile


class PortablePreferencesTests(unittest.TestCase):
    def test_relocated_app_uses_user_application_support(self):
        with tempfile.TemporaryDirectory() as folder:
            profile = profile_path(frozen=True, home=folder)
            self.assertEqual(profile, Path(folder) / 'Library/Application Support/Head Mouse/profile.json')
            self.assertFalse(profile.parent.exists())
            save_profile(22, .8, [1,0,0], [0,1,0], profile, mode_set='Mode 2', transport='Bluetooth')
            restored = load_profile(profile)
            self.assertEqual(restored['right'], [1,0,0])
            self.assertEqual(restored['mode_set'], 'Mode 2')
            self.assertEqual(restored['transport'], 'Bluetooth')
            self.assertEqual(list(profile.parent.iterdir()), [profile])

    def test_development_profile_remains_separate_from_installed_app(self):
        self.assertEqual(profile_path(frozen=False).parent, Path(__file__).resolve().parent)
        self.assertNotEqual(profile_path(frozen=False), profile_path(frozen=True))
