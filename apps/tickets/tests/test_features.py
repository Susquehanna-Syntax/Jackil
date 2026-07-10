from config.features import enabled_features, feature_enabled


class FeatureRegistryTests:
    def test_enabled_features_includes_installed(self):
        features = enabled_features()
        assert "sla" in features
        assert "automation" in features
        assert "customfields" in features
        assert "api" in features
        assert "reports" in features

    def test_feature_enabled_true_for_installed(self):
        assert feature_enabled("automation") is True

    def test_feature_enabled_false_for_unknown(self):
        assert feature_enabled("nonexistent_feature") is False
