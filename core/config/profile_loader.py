import os

import yaml


class ProfileLoader:
    """Load device profiles without coupling the ingestion pipeline to a file."""

    def __init__(self, base_dir, default_profile="arduino_uno.yaml"):
        self.profiles_dir = os.path.join(base_dir, "profiles")
        self.default_profile = default_profile

    def load(self, profile_name=None):
        selected_profile = profile_name or self.default_profile
        profile_path = os.path.join(self.profiles_dir, selected_profile)
        with open(profile_path, "r") as profile_file:
            profile = yaml.safe_load(profile_file) or {}
        profile["profile_path"] = profile_path
        return profile