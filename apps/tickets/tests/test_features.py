from django.test import SimpleTestCase

from config.features import enabled_features, feature_enabled


class FeatureRegistryTests(SimpleTestCase):
    def test_enabled_features_includes_installed(self):
        features = enabled_features()
        self.assertIn("sla", features)
        self.assertIn("automation", features)
        self.assertIn("customfields", features)
        self.assertIn("api", features)
        self.assertIn("reports", features)

    def test_feature_enabled_true_for_installed(self):
        self.assertIs(feature_enabled("automation"), True)

    def test_feature_enabled_false_for_unknown(self):
        self.assertIs(feature_enabled("nonexistent_feature"), False)
